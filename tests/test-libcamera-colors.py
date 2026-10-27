#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prove the packed CCM and padded gamma lookup equal the original arithmetic."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path, help='libcamera tree with the color-only patch')
args = parser.parse_args()
code = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <iostream>
#include <random>
#include "libcamera/internal/software_isp/packed_ccm.h"
using namespace libcamera;
int main()
{
    std::array<uint8_t, 256> gamma;
    std::array<uint8_t, kCcmGammaSize> padded;
    for (unsigned i=0; i<256; i++) gamma[i]=(i*73+31)&255;
    std::fill(padded.begin(),padded.begin()+kCcmGammaOffset,gamma.front());
    std::copy(gamma.begin(),gamma.end(),padded.begin()+kCcmGammaOffset);
    std::fill(padded.begin()+kCcmGammaOffset+256,padded.end(),gamma.back());
    for (unsigned i=0; i<kCcmGammaSize; i++)
        assert(padded[i]==gamma[std::clamp(int(i)-int(kCcmGammaOffset),0,255)]);
    std::mt19937 random(0x8550);
    for (unsigned trial=0; trial<200000; trial++) {
        int16_t column[3][3];
        for (auto &c:column) for (auto &v:c) v=static_cast<int16_t>(random());
        if (trial<2) for(auto &c:column) for(auto &v:c) v=trial ? INT16_MAX : INT16_MIN;
        uint64_t sum=0;
        for (auto &c:column) sum+=packCcmColumn(c[2],c[1],c[0]);
        for (unsigned channel=0; channel<3; channel++) {
            int reference=int(column[0][channel])+column[1][channel]+column[2][channel];
            unsigned index=packedCcmIndex(sum,channel);
            assert(index<kCcmGammaSize);
            assert(int(index)-int(kCcmGammaOffset)==reference);
            assert(padded[index]==gamma[std::clamp(reference,0,255)]);
        }
    }
    std::cout<<"PASS: all gamma indices, full int16 endpoints, 200000 signed CCM triples, no inter-channel carries, exact original output\n";
}
'''
with tempfile.TemporaryDirectory(prefix='vermeer-color-test-') as directory:
    directory = Path(directory)
    source = directory / 'test.cpp'
    source.write_text(code)
    binary = directory / 'test'
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-g', '-I',
                    str(args.source.resolve() / 'include'), str(source),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
