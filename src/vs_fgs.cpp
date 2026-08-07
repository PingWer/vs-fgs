#include "VapourSynth4.h"
#include "VSHelper4.h"
#include <cstring>
#include <new>

extern "C" {
#define BITDEPTH 16
#include "dav1d/headers.h"
#include "dav1d/picture.h"
#include "src/filmgrain.h"
#include "src/cpu.h"
void dav1d_apply_grain_8bpc(const Dav1dFilmGrainDSPContext *const dsp, Dav1dPicture *const out, const Dav1dPicture *const in);
void dav1d_apply_grain_16bpc(const Dav1dFilmGrainDSPContext *const dsp, Dav1dPicture *const out, const Dav1dPicture *const in);
}
#include <vector>
#include <algorithm>
#include "cherry_seeds.h"

struct FGSData {
    VSNode *node;
    const VSVideoInfo *vi;
    std::vector<Dav1dFilmGrainData> fg_data_array;
    Dav1dFilmGrainDSPContext dsp_8bpc;
    Dav1dFilmGrainDSPContext dsp_16bpc;
    Dav1dPictureParameters pic_params;
    Dav1dSequenceHeader seq_hdr;
    bool is_8bpc;
    bool is_yuv;
    int dynamic_seed;
    int seed_list;
};

static const VSFrame *VS_CC vs_fgs_get_frame(int n, int activationReason, void *instanceData, void **frameData, VSFrameContext *frameCtx, VSCore *core, const VSAPI *vsapi) {
    FGSData *d = (FGSData *)instanceData;

    if (activationReason == arInitial) {
        vsapi->requestFrameFilter(n, d->node, frameCtx);
    } else if (activationReason == arAllFramesReady) {
        const VSFrame *src = vsapi->getFrameFilter(n, d->node, frameCtx);
        if (!src) return nullptr;
        
        VSFrame *dst = vsapi->newVideoFrame(&d->vi->format, d->vi->width, d->vi->height, src, core);
        
        Dav1dPicture in_pic = {};
        Dav1dPicture out_pic = {};
        
        in_pic.p = d->pic_params;
        
        in_pic.data[0] = (void*)vsapi->getReadPtr(src, 0);
        in_pic.stride[0] = vsapi->getStride(src, 0);
        if (d->is_yuv) {
            in_pic.data[1] = (void*)vsapi->getReadPtr(src, 1);
            in_pic.data[2] = (void*)vsapi->getReadPtr(src, 2);
            in_pic.stride[1] = vsapi->getStride(src, 1);
        }
        
        Dav1dFrameHeader hdr = {};
        
        size_t idx = std::min((size_t)n, d->fg_data_array.size() - 1);
        Dav1dFilmGrainData fd = d->fg_data_array[idx];
        
        if (d->dynamic_seed) {
            if (d->seed_list == 1) {
                fd.seed = NETFLIX_SEEDS[n % NUM_NETFLIX_SEEDS];
            } else {
                fd.seed = IGOR_SEEDS[n % NUM_IGOR_SEEDS];
            }
        }
        
        VSMap *props = vsapi->getFramePropertiesRW(dst);
        vsapi->mapSetInt(props, "FGS_Seed", fd.seed, maReplace);

        hdr.film_grain.data = fd;
        hdr.film_grain.present = 1;
        in_pic.frame_hdr = &hdr;
        in_pic.seq_hdr = &d->seq_hdr;
        
        out_pic = in_pic;
        out_pic.data[0] = (void*)vsapi->getWritePtr(dst, 0);
        out_pic.stride[0] = vsapi->getStride(dst, 0);
        if (d->is_yuv) {
            out_pic.data[1] = (void*)vsapi->getWritePtr(dst, 1);
            out_pic.data[2] = (void*)vsapi->getWritePtr(dst, 2);
            out_pic.stride[1] = vsapi->getStride(dst, 1);
        }
        out_pic.frame_hdr = &hdr;
        
        if (d->is_8bpc) {
            dav1d_apply_grain_8bpc(&d->dsp_8bpc, &out_pic, &in_pic);
        } else {
            dav1d_apply_grain_16bpc(&d->dsp_16bpc, &out_pic, &in_pic);
        }
        
        vsapi->freeFrame(src);
        return dst;
    }
    return nullptr;
}

static void VS_CC vs_fgs_free(void *instanceData, VSCore *core, const VSAPI *vsapi) {
    FGSData *d = (FGSData *)instanceData;
    vsapi->freeNode(d->node);
    delete d;
}

static void VS_CC vs_fgs_create(const VSMap *in, VSMap *out, void *userData, VSCore *core, const VSAPI *vsapi) {
    FGSData *d = new (std::nothrow) FGSData{};
    if (!d) {
        vsapi->mapSetError(out, "vsfgs: memory allocation failed");
        return;
    }
    
    d->node = vsapi->mapGetNode(in, "clip", 0, nullptr);
    d->vi = vsapi->getVideoInfo(d->node);
    
    if (!vsh::isConstantVideoFormat(d->vi) || 
        d->vi->format.colorFamily != cfYUV ||
        (d->vi->format.bitsPerSample != 8 && d->vi->format.bitsPerSample != 10 && d->vi->format.bitsPerSample != 12)) {
        vsapi->mapSetError(out, "vsfgs: only constant format 8, 10, or 12-bit YUV is supported.");
        vsapi->freeNode(d->node);
        delete d;
        return;
    }

    if (d->vi->format.colorFamily == cfYUV) {
        if (!((d->vi->format.subSamplingW == 1 && d->vi->format.subSamplingH == 1) ||
              (d->vi->format.subSamplingW == 1 && d->vi->format.subSamplingH == 0) ||
              (d->vi->format.subSamplingW == 0 && d->vi->format.subSamplingH == 0))) {
            vsapi->mapSetError(out, "vsfgs: only 420, 422, and 444 subsampling are supported for YUV.");
            vsapi->freeNode(d->node);
            delete d;
            return;
        }
    }
    
    int size = vsapi->mapGetDataSize(in, "fgs_data", 0, nullptr);
    if (size == 0 || size % sizeof(Dav1dFilmGrainData) != 0) {
        vsapi->mapSetError(out, "vsfgs: fgs_data size mismatch");
        vsapi->freeNode(d->node);
        delete d;
        return;
    }
    
    int num_items = size / sizeof(Dav1dFilmGrainData);
    d->fg_data_array.resize(num_items);
    
    const char *data_ptr = vsapi->mapGetData(in, "fgs_data", 0, nullptr);
    std::memcpy(d->fg_data_array.data(), data_ptr, size);
    
    d->dynamic_seed = vsapi->mapGetIntSaturated(in, "dynamic_seed", 0, nullptr);
    d->seed_list = vsapi->mapGetIntSaturated(in, "seed_list", 0, nullptr);
    
    int err = 0;
    int64_t simd_mask_val = vsapi->mapGetInt(in, "simd_mask", 0, &err);
    unsigned simd_mask = (err || simd_mask_val < 0) ? ~0U : (unsigned)simd_mask_val;

    dav1d_init_cpu();
    dav1d_set_cpu_flags_mask(simd_mask);
    
    d->is_8bpc = (d->vi->format.bitsPerSample == 8);
    d->is_yuv = (d->vi->format.colorFamily == cfYUV);
    
    d->pic_params.w = d->vi->width;
    d->pic_params.h = d->vi->height;
    d->pic_params.bpc = d->vi->format.bitsPerSample;
    if (d->vi->format.colorFamily == cfGray) d->pic_params.layout = DAV1D_PIXEL_LAYOUT_I400;
    else if (d->vi->format.subSamplingW == 1 && d->vi->format.subSamplingH == 1) d->pic_params.layout = DAV1D_PIXEL_LAYOUT_I420;
    else if (d->vi->format.subSamplingW == 1 && d->vi->format.subSamplingH == 0) d->pic_params.layout = DAV1D_PIXEL_LAYOUT_I422;
    else if (d->vi->format.subSamplingW == 0 && d->vi->format.subSamplingH == 0) d->pic_params.layout = DAV1D_PIXEL_LAYOUT_I444;
    
    d->seq_hdr.mtrx = DAV1D_MC_UNKNOWN;

    if (d->is_8bpc) {
        dav1d_film_grain_dsp_init_8bpc(&d->dsp_8bpc);
    } else {
        dav1d_film_grain_dsp_init_16bpc(&d->dsp_16bpc);
    }
    
    VSFilterDependency deps[] = {{d->node, rpStrictSpatial}};
    vsapi->createVideoFilter(out, "FGS", d->vi, vs_fgs_get_frame, vs_fgs_free, fmParallel, deps, 1, d, core);
}

VS_EXTERNAL_API(void) VapourSynthPluginInit2(VSPlugin *plugin, const VSPLUGINAPI *vspapi) {
    dav1d_init_cpu();
    vspapi->configPlugin("com.vs.fgs", "fgs", "Film Grain Synthesis via dav1d", VS_MAKE_VERSION(1, 0), VS_MAKE_VERSION(4, 0), 0, plugin);
    vspapi->registerFunction("FGS", "clip:vnode;fgs_data:data;dynamic_seed:int:opt;simd_mask:int:opt;seed_list:int:opt;", "clip:vnode;", vs_fgs_create, nullptr, plugin);
}
