#include <windows.h>
#include <dbghelp.h>

#include <cstdio>
#include <string>

#pragma comment(lib, "Dbghelp.lib")

namespace {

std::wstring take_value(int argc, wchar_t** argv, const wchar_t* name) {
  for (int i = 1; i + 1 < argc; ++i) {
    if (std::wstring(argv[i]) == name) {
      return argv[i + 1];
    }
  }
  return {};
}

const char* architecture(USHORT processor_architecture) {
  switch (processor_architecture) {
    case PROCESSOR_ARCHITECTURE_AMD64:
      return "x86_64";
    case PROCESSOR_ARCHITECTURE_INTEL:
      return "x86";
    case PROCESSOR_ARCHITECTURE_ARM64:
      return "arm64";
    default:
      return "unknown";
  }
}

const char* access_type(ULONG parameter) {
  switch (parameter) {
    case 0:
      return "read";
    case 1:
      return "write";
    case 8:
      return "execute";
    default:
      return "unknown";
  }
}

void print_hex_u64(ULONG64 value) {
  std::printf("0x%016llX", static_cast<unsigned long long>(value));
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  const std::wstring path = take_value(argc, argv, L"--dump");
  if (path.empty()) {
    std::fwprintf(stderr, L"usage: verify_golden_minidump.exe --dump <file>\n");
    return 2;
  }

  HANDLE file = CreateFileW(path.c_str(), GENERIC_READ,
                            FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    std::printf("{\"valid_dump\":false,\"error\":\"CreateFileW\",\"win32_error\":%lu}\n",
                GetLastError());
    return 3;
  }
  LARGE_INTEGER file_size{};
  if (!GetFileSizeEx(file, &file_size) ||
      file_size.QuadPart < static_cast<LONGLONG>(sizeof(MINIDUMP_HEADER))) {
    std::printf("{\"valid_dump\":false,\"error\":\"truncated_header\"}\n");
    CloseHandle(file);
    return 4;
  }
  HANDLE mapping = CreateFileMappingW(file, nullptr, PAGE_READONLY, 0, 0,
                                      nullptr);
  if (mapping == nullptr) {
    std::printf("{\"valid_dump\":false,\"error\":\"CreateFileMappingW\",\"win32_error\":%lu}\n",
                GetLastError());
    CloseHandle(file);
    return 5;
  }
  auto* base = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0);
  if (base == nullptr) {
    std::printf("{\"valid_dump\":false,\"error\":\"MapViewOfFile\",\"win32_error\":%lu}\n",
                GetLastError());
    CloseHandle(mapping);
    CloseHandle(file);
    return 6;
  }

  auto* header = static_cast<MINIDUMP_HEADER*>(base);
  if (header->Signature != MINIDUMP_SIGNATURE) {
    std::printf("{\"valid_dump\":false,\"error\":\"bad_magic\",\"signature\":%lu}\n",
                header->Signature);
    UnmapViewOfFile(base);
    CloseHandle(mapping);
    CloseHandle(file);
    return 7;
  }

  PMINIDUMP_DIRECTORY directory = nullptr;
  PVOID stream_pointer = nullptr;
  ULONG stream_size = 0;
  auto read_stream = [&](MINIDUMP_STREAM_TYPE type) -> bool {
    directory = nullptr;
    stream_pointer = nullptr;
    stream_size = 0;
    return MiniDumpReadDumpStream(base, type, &directory, &stream_pointer,
                                  &stream_size) != FALSE;
  };

  MINIDUMP_SYSTEM_INFO* system_info = nullptr;
  if (read_stream(SystemInfoStream) &&
      stream_size >= sizeof(MINIDUMP_SYSTEM_INFO)) {
    system_info = static_cast<MINIDUMP_SYSTEM_INFO*>(stream_pointer);
  }
  MINIDUMP_EXCEPTION_STREAM* exception_stream = nullptr;
  if (read_stream(ExceptionStream) &&
      stream_size >= sizeof(MINIDUMP_EXCEPTION_STREAM)) {
    exception_stream = static_cast<MINIDUMP_EXCEPTION_STREAM*>(stream_pointer);
  }
  MINIDUMP_THREAD_LIST* thread_list = nullptr;
  if (read_stream(ThreadListStream) &&
      stream_size >= sizeof(ULONG) + sizeof(MINIDUMP_THREAD)) {
    thread_list = static_cast<MINIDUMP_THREAD_LIST*>(stream_pointer);
  }
  MINIDUMP_MODULE_LIST* module_list = nullptr;
  if (read_stream(ModuleListStream) &&
      stream_size >= sizeof(ULONG) + sizeof(MINIDUMP_MODULE)) {
    module_list = static_cast<MINIDUMP_MODULE_LIST*>(stream_pointer);
  }

  const char* arch = system_info == nullptr
                         ? "unknown"
                         : architecture(system_info->ProcessorArchitecture);
  const bool has_exception = exception_stream != nullptr;
  const ULONG exception_code =
      has_exception ? exception_stream->ExceptionRecord.ExceptionCode : 0;
  const ULONG parameter_count =
      has_exception ? exception_stream->ExceptionRecord.NumberParameters : 0;
  const ULONG64 access_parameter =
      parameter_count > 0
          ? exception_stream->ExceptionRecord.ExceptionInformation[0]
          : 0;
  const ULONG64 fault_address =
      parameter_count > 1
          ? exception_stream->ExceptionRecord.ExceptionInformation[1]
          : 0;
  const bool structurally_complete = system_info != nullptr &&
                                     thread_list != nullptr &&
                                     module_list != nullptr;

  std::printf("{\"valid_dump\":%s,\"structurally_complete\":%s,\"magic_ascii\":\"MDMP\",\"architecture\":\"%s\",",
              structurally_complete ? "true" : "false",
              structurally_complete ? "true" : "false", arch);
  std::printf("\"has_exception\":%s,\"exception\":",
              has_exception ? "true" : "false");
  if (!has_exception) {
    std::printf("null");
  } else {
    std::printf("{\"code\":\"");
    std::printf("0x%08lX", exception_code);
    std::printf("\",\"access_type\":\"%s\",\"fault_address\":\"",
                access_type(static_cast<ULONG>(access_parameter)));
    print_hex_u64(fault_address);
    std::printf("\",\"exception_address\":\"");
    print_hex_u64(exception_stream->ExceptionRecord.ExceptionAddress);
    std::printf("\"}");
  }
  std::printf(",\"crashing_thread\":");
  if (has_exception) {
    std::printf("{\"thread_id\":%lu}", exception_stream->ThreadId);
  } else {
    std::printf("null");
  }
  std::printf(",\"thread_count\":%lu,\"module_count\":%lu,\"header_version\":%lu}\n",
              structurally_complete && thread_list != nullptr
                  ? static_cast<ULONG>(thread_list->NumberOfThreads)
                  : 0UL,
              structurally_complete && module_list != nullptr
                  ? static_cast<ULONG>(module_list->NumberOfModules)
                  : 0UL,
              header->Version);

  UnmapViewOfFile(base);
  CloseHandle(mapping);
  CloseHandle(file);
  return 0;
}
