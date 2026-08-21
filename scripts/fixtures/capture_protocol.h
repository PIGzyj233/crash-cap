#pragma once

#include <windows.h>

#include <cstdint>

namespace crashcap {

constexpr std::uint32_t kContextSnapshotMagic = 0x43524350;  // CRCP
constexpr std::uint32_t kContextSnapshotVersion = 1;

// This is an on-disk hand-off between the target's unhandled-exception filter
// and the independent collector. Both programs are built by the same MSVC
// toolchain; the version/magic fields make accidental reuse detectable.
struct ContextSnapshot {
  std::uint32_t magic = kContextSnapshotMagic;
  std::uint32_t version = kContextSnapshotVersion;
  std::uint32_t process_id = 0;
  std::uint32_t thread_id = 0;
  EXCEPTION_RECORD exception_record{};
  CONTEXT context{};
};

}  // namespace crashcap
