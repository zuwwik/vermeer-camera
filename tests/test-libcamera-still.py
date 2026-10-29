#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Test the actual offline RAW processor with sanitizers and synthetic inputs."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
args = parser.parse_args()
root = args.source.resolve()
code = r'''
#include <libcamera/still_image.h>
#include <cassert>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <random>
using namespace libcamera;
static void set(std::vector<uint8_t>& v,unsigned stride,unsigned x,unsigned y,unsigned value) {
    size_t i=y*stride+x/4*5;v[i+x%4]=value>>2;
    v[i+4]=(v[i+4]&~(3<<(2*(x%4))))|((value&3)<<(2*(x%4)));
}
int main() {
    StillImageParameters p;p.width=64;p.height=48;p.stride=96;p.gamma=1;
    p.denoise=p.sharpen=p.highlightRolloff=false;
    std::vector<uint8_t> raw(p.stride*p.height,177);
    int pattern[4][4]={{2,1,1,0},{1,2,0,1},{1,0,2,1},{0,1,1,2}};
    int value[3]={601,402,203};
    for(unsigned order=0;order<4;order++) {
        p.order=static_cast<StillBayerOrder>(order);
        for(unsigned y=0;y<p.height;y++)for(unsigned x=0;x<p.width;x++)
            set(raw,p.stride,x,y,value[pattern[order][(y&1)*2+(x&1)]]);
        StillImage image;assert(!StillImageProcessor::processRaw10(raw.data(),raw.size(),p,&image));
        assert(image.width==p.width&&image.height==p.height&&image.rgb.size()==p.width*p.height*3);
        for(unsigned y=0;y<p.height;y++)for(unsigned x=0;x<p.width;x++)for(int c=0;c<3;c++)
            assert(std::abs(int(image.rgb[(y*p.width+x)*3+c])-int(std::lround((value[c]-64)/959.*255)))<=1);
    }
    // With WB gains > 1, sensor-clipped white must stay neutral through
    // the same pre-CCM clipping as preview (all four Bayer arrangements).
    p.whiteBalance={2.1f,1.f,1.7f};
    p.colorMatrix={1.3112f,-.1756f,-.1356f,-.2344f,1.5474f,-.313f,-.0504f,-.6847f,1.7351f};
    p.gamma=2.2f;p.denoise=p.sharpen=p.highlightRolloff=true;
    for(unsigned order=0;order<4;order++) {
        p.order=static_cast<StillBayerOrder>(order);
        for(unsigned y=0;y<p.height;y++)for(unsigned x=0;x<p.width;x++)set(raw,p.stride,x,y,1023);
        StillImage white;assert(!StillImageProcessor::processRaw10(raw.data(),raw.size(),p,&white));
        for(size_t i=0;i<white.rgb.size();i+=3) {
            int lo=std::min({white.rgb[i],white.rgb[i+1],white.rgb[i+2]});
            int hi=std::max({white.rgb[i],white.rgb[i+1],white.rgb[i+2]});
            assert(lo>=248 && hi-lo<=1);
        }
    }
    // Compare coloured patches, including a clipped R or B channel, to
    // independent black level -> WB -> clip -> CCM -> gamma arithmetic.
    p.gamma=1;p.denoise=p.sharpen=p.highlightRolloff=false;
    for(auto values : {std::array<int,3>{750,850,700}, {900,400,300}, {300,400,900}, {180,300,140}}) {
        for(unsigned y=0;y<p.height;y++)for(unsigned x=0;x<p.width;x++)
            set(raw,p.stride,x,y,values[pattern[3][(y&1)*2+(x&1)]]);
        StillImage patch;assert(!StillImageProcessor::processRaw10(raw.data(),raw.size(),p,&patch));
        for(unsigned c=0;c<3;c++) {
            float linear=0;
            for(unsigned k=0;k<3;k++)linear+=std::clamp((values[k]-64)/959.f*p.whiteBalance[k],0.f,1.f)*p.colorMatrix[c*3+k];
            int reference=std::lround(std::clamp(linear,0.f,1.f)*255);
            for(size_t i=c;i<patch.rgb.size();i+=3)assert(std::abs(int(patch.rgb[i])-reference)<=1);
        }
    }
    p.whiteBalance={1,1,1};p.colorMatrix={1,0,0,0,1,0,0,0,1};
    p.width=256;p.height=128;p.stride=352;p.analogueGain=16;
    raw.assign(p.stride*p.height,0);std::mt19937 rng(17);std::normal_distribution<double> noise(0,8);
    for(unsigned y=0;y<p.height;y++)for(unsigned x=0;x<p.width;x++)set(raw,p.stride,x,y,std::clamp(int(400+noise(rng)),0,1023));
    StillImage before,after;assert(!StillImageProcessor::processRaw10(raw.data(),raw.size(),p,&before));
    p.denoise=true;assert(!StillImageProcessor::processRaw10(raw.data(),raw.size(),p,&after));
    double a=0,b=0,expected=(400-64)/959.*255;
    for(unsigned y=4;y+4<p.height;y++)for(unsigned x=4;x+4<p.width;x++)for(int c=0;c<3;c++) {
        a+=std::pow(before.rgb[(y*p.width+x)*3+c]-expected,2);
        b+=std::pow(after.rgb[(y*p.width+x)*3+c]-expected,2);
    }
    std::cout<<"noise variance ratio "<<b/a<<'\n';assert(b<a*.9);
    std::vector<std::vector<uint8_t>> burst(3,raw);
    for(unsigned f=1;f<3;f++)for(unsigned y=0;y<p.height;y++)for(unsigned x=0;x<p.width;x++)
        set(burst[f],p.stride,x,y,std::clamp(int(400+noise(rng)),0,1023));
    std::vector<StillRawFrame> frames;
    for(auto &data:burst)frames.push_back({data.data(),data.size(),p});
    StillImage merged;assert(!StillImageProcessor::processRaw10Burst(frames,&merged));
    double mergedError=0;
    for(unsigned y=4;y+4<p.height;y++)for(unsigned x=4;x+4<p.width;x++)for(int c=0;c<3;c++)
        mergedError+=std::pow(merged.rgb[(y*p.width+x)*3+c]-expected,2);
    std::cout<<"burst noise variance ratio "<<mergedError/a<<'\n';assert(mergedError<b);
    // Brightness transitions must not blend frames with a different exposure.
    frames[0].parameters.exposureProduct=100;frames[1].parameters.exposureProduct=200;frames[2].parameters.exposureProduct=300;
    assert(!StillImageProcessor::processRaw10Burst(frames,&merged));
    assert(merged.rgb==after.rgb);
    p.sharpen=p.highlightRolloff=true;p.gamma=2.2;
    assert(!StillImageProcessor::processRaw10(raw.data(),raw.size(),p,&after));
    assert(StillImageProcessor::processRaw10(raw.data(),raw.size()-1,p,&after)<0&&after.rgb.empty());
    p.gamma=NAN;assert(StillImageProcessor::processRaw10(raw.data(),raw.size(),p,&after)<0);
    std::cout<<"PASS: all CFA orders, RAW10 low bits, full dimensions, padded strides, borders, denoise, tone/sharpen, invalid inputs\n";
}
'''
with tempfile.TemporaryDirectory(prefix='vermeer-still-test-') as directory:
    directory = Path(directory)
    (directory / 'test.cpp').write_text(code)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-g', '-I', str(root / 'include'),
                    str(directory / 'test.cpp'), str(root / 'src/libcamera/still_image.cpp'),
                    '-o', str(directory / 'test')], check=True)
    subprocess.run([str(directory / 'test')], check=True)
