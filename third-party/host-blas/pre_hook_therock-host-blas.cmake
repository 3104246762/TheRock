# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

# Fork workaround for a Windows build failure in the host-blas (OpenBLAS)
# subproject when it is compiled with AMD clang-cl (therock's amd-llvm
# 24.0.0git) and linked with the MSVC linker:
#
#   CVTRES : fatal error CVT1107: ...\cungql.c.obj
#   LINK   : fatal error LNK1123: failure during conversion to COFF: file invalid or corrupt
#
# The cvtres.exe shipped with VS 2022 (MSVC 14.44 / 17.14) cannot embed a
# manifest into the COFF objects that this clang-cl emits, so the final link of
# rocm-openblas.dll fails. Embedding a manifest is unnecessary for ROCm's
# runtime DLLs, so we disable manifest embedding.
#
# We patch the *_INIT linker variables (not the plain CMAKE_*_LINKER_FLAGS)
# because the therock Windows + clang toolchain deliberately resets the
# non-INIT CMAKE_*_LINKER_FLAGS to empty (see cmake/therock_subproject.cmake,
# the "MSVC AND compiler_toolchain" branch), and CMake seeds the real
# CMAKE_*_LINKER_FLAGS from the *_INIT values.

if(WIN32)
  foreach(_var CMAKE_SHARED_LINKER_FLAGS_INIT CMAKE_EXE_LINKER_FLAGS_INIT CMAKE_MODULE_LINKER_FLAGS_INIT)
    if(NOT "${${_var}}" MATCHES "/MANIFEST:NO")
      string(APPEND ${_var} " /MANIFEST:NO")
    endif()
  endforeach()
  message(STATUS "host-blas pre_hook: appended /MANIFEST:NO to linker *_INIT flags (workaround for LNK1123/CVT1107)")
endif()
