#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual lens activation and V4L2 reopen code with failing devices."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def function(source, name):
    start = source.index('int ' + name + '(')
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Private patched libcamera source')
    args = parser.parse_args()
    code = r'''
#include <cassert>
#include <cerrno>
#include <memory>
#include <utility>
#include <vector>
#include <iostream>
struct UniqueFD {
 int value=-1;
 UniqueFD()=default;
 explicit UniqueFD(int v):value(v){}
 UniqueFD(UniqueFD&& o):value(std::exchange(o.value,-1)){}
 UniqueFD& operator=(UniqueFD&& o){value=std::exchange(o.value,-1);return *this;}
 bool isValid()const{return value>=0;}
 int get()const{return value;}
 void reset(){value=-1;}
};
struct Signal {template<class T,class U>void connect(T*,U){}};
struct EventNotifier {
 enum Type {Exception}; Signal activated;
 EventNotifier(int,Type){}
 void setEnabled(bool){}
};
class V4L2Device {
public:
 UniqueFD fd_;std::unique_ptr<EventNotifier>fdEventNotifier_;
 std::vector<std::unique_ptr<int>>controlIds_;
 int enumerations=0,updates=0;
 bool isOpen()const{return fd_.isValid();}
 void close(){fdEventNotifier_.reset();fd_.reset();}
 void eventAvailable(){}
 void listControls(){enumerations++;controlIds_.push_back(std::make_unique<int>(123));}
 void updateControlInfo(){updates++;}
 int setFd(UniqueFD fd);
};
struct V4L2Subdevice:V4L2Device {
 bool fail=false;int opens=0;
 int open(){opens++;int r=setFd(UniqueFD(42));return r?r:fail?-EIO:0;}
};
struct CameraLens {
 std::unique_ptr<V4L2Subdevice>subdev_=std::make_unique<V4L2Subdevice>();
 int setActive(bool);
};
'''
    code += function((args.source / 'src/libcamera/v4l2_device.cpp').read_text(),
                     'V4L2Device::setFd') + '\n'
    code += function((args.source / 'src/libcamera/camera_lens.cpp').read_text(),
                     'CameraLens::setActive') + '\n'
    code += r'''
int main(){
 CameraLens lens;auto&d=*lens.subdev_;
 assert(!lens.setActive(false));assert(!d.isOpen());
 assert(!lens.setActive(true));assert(d.isOpen()&&d.opens==1&&d.enumerations==1);
 const int *cached=d.controlIds_.front().get();
 assert(!lens.setActive(true));assert(d.opens==1);
 assert(d.setFd(UniqueFD(77))==-EBUSY);
 for(int i=0;i<200;i++){
  assert(!lens.setActive(false));assert(!d.isOpen());
  assert(*cached==123);assert(!lens.setActive(true));
  assert(d.isOpen());assert(d.controlIds_.size()==1);
  assert(d.controlIds_.front().get()==cached);
 }
 assert(d.enumerations==1&&d.updates==200);
 lens.setActive(false);d.fail=true;
 assert(lens.setActive(true)==-EIO);assert(!d.isOpen());
 d.fail=false;assert(!lens.setActive(true));assert(d.isOpen());
 assert(*cached==123);lens.setActive(false);
 std::cout<<"PASS: 200 lens close/open cycles, stable ControlId cache, idempotent activation, failed-open cleanup and recovery\n";
}
'''
    with tempfile.TemporaryDirectory(prefix='vermeer-lens-test-') as temp:
        root = Path(temp)
        (root / 'test.cpp').write_text(code)
        subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(root / 'test.cpp'),
                        '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
