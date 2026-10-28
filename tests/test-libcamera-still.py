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
