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
    std::fwprintf(stderr, L"usage: verify_minidump.exe --dump <file>\n");
    return 2;
  }

  HANDLE file = CreateFileW(path.c_str(), GENERIC_READ,
                            FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    std::printf("{\"ok\":false,\"error\":\"CreateFileW\",\"win32_error\":%lu}\n",
                GetLastError());
    return 3;
  }
  HANDLE mapping = CreateFileMappingW(file, nullptr, PAGE_READONLY, 0, 0,
                                      nullptr);
  if (mapping == nullptr) {
    std::printf("{\"ok\":false,\"error\":\"CreateFileMappingW\",\"win32_error\":%lu}\n",
                GetLastError());
    CloseHandle(file);
    return 4;
  }
  auto* base = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0);
  if (base == nullptr) {
    std::printf("{\"ok\":false,\"error\":\"MapViewOfFile\",\"win32_error\":%lu}\n",
                GetLastError());
    CloseHandle(mapping);
    CloseHandle(file);
    return 5;
  }

  auto* header = static_cast<MINIDUMP_HEADER*>(base);
  if (header->Signature != MINIDUMP_SIGNATURE) {
    std::printf("{\"ok\":false,\"error\":\"bad_magic\",\"signature\":%lu}\n",
                header->Signature);
    UnmapViewOfFile(base);
    CloseHandle(mapping);
    CloseHandle(file);
    return 6;
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

  if (!read_stream(MemoryInfoListStream)) {
    // MemoryInfoListStream is optional for older dump writers; do not fail
    // solely because a valid MiniDump omitted it.
  }

  MINIDUMP_SYSTEM_INFO* system_info = nullptr;
  if (read_stream(SystemInfoStream)) {
    system_info = static_cast<MINIDUMP_SYSTEM_INFO*>(stream_pointer);
  }
  MINIDUMP_EXCEPTION_STREAM* exception_stream = nullptr;
  if (read_stream(ExceptionStream)) {
    exception_stream = static_cast<MINIDUMP_EXCEPTION_STREAM*>(stream_pointer);
  }
  MINIDUMP_THREAD_LIST* thread_list = nullptr;
  if (read_stream(ThreadListStream)) {
    thread_list = static_cast<MINIDUMP_THREAD_LIST*>(stream_pointer);
  }
  MINIDUMP_MODULE_LIST* module_list = nullptr;
  if (read_stream(ModuleListStream)) {
    module_list = static_cast<MINIDUMP_MODULE_LIST*>(stream_pointer);
  }
  const bool amd64 = system_info != nullptr &&
                     system_info->ProcessorArchitecture ==
                         PROCESSOR_ARCHITECTURE_AMD64;
  const bool has_exception = exception_stream != nullptr;
  const MINIDUMP_MODULE* fault_module = nullptr;
  if (module_list != nullptr && has_exception) {
    const ULONG64 exception_address =
        exception_stream->ExceptionRecord.ExceptionAddress;
    for (ULONG index = 0; index < module_list->NumberOfModules; ++index) {
      const MINIDUMP_MODULE* module = &module_list->Modules[index];
      const ULONG64 module_end =
          module->BaseOfImage + static_cast<ULONG64>(module->SizeOfImage);
      if (exception_address >= module->BaseOfImage &&
          exception_address < module_end) {
        fault_module = module;
        break;
      }
    }
  }
  const bool has_thread = has_exception && exception_stream->ThreadId != 0;
  const ULONG exception_code =
      has_exception ? exception_stream->ExceptionRecord.ExceptionCode : 0;
  const ULONG parameter_count = has_exception
                                    ? exception_stream->ExceptionRecord.NumberParameters
                                    : 0;
  const ULONG64 access_parameter =
      parameter_count > 0
          ? exception_stream->ExceptionRecord.ExceptionInformation[0]
          : 0;
  const ULONG64 fault_address =
      parameter_count > 1
          ? exception_stream->ExceptionRecord.ExceptionInformation[1]
          : 0;
  const bool ok = amd64 && has_exception && has_thread &&
                  exception_code == EXCEPTION_ACCESS_VIOLATION &&
                  parameter_count >= 2 && access_parameter == 0 &&
                  fault_address == 0;

  std::printf("{\"ok\":%s,\"magic_ascii\":\"MDMP\",\"architecture\":\"%s\",",
              ok ? "true" : "false", amd64 ? "x86_64" : "unknown");
  std::printf("\"exception\":{\"code\":\"");
  std::printf("0x%08lX", exception_code);
  std::printf("\",\"name\":\"%s\",\"access_type\":\"%s\",\"fault_address\":\"",
              exception_code == EXCEPTION_ACCESS_VIOLATION
                  ? "EXCEPTION_ACCESS_VIOLATION"
                  : "unknown",
              access_type(static_cast<ULONG>(access_parameter)));
  print_hex_u64(fault_address);
  std::printf("\"},\"exception_address\":\"");
  print_hex_u64(has_exception ? exception_stream->ExceptionRecord.ExceptionAddress : 0);
  std::printf("\",\"crashing_thread\":{\"thread_id\":%lu},",
              has_exception ? exception_stream->ThreadId : 0UL);
  std::printf("\"fault_module\":{\"image_base\":\"");
  print_hex_u64(fault_module != nullptr ? fault_module->BaseOfImage : 0);
  std::printf("\",\"image_size\":%lu},",
              fault_module != nullptr ? fault_module->SizeOfImage : 0UL);
  std::printf("\"thread_count\":%lu,\"module_count\":%lu,\"header_version\":%lu}\n",
              thread_list != nullptr ? thread_list->NumberOfThreads : 0UL,
              module_list != nullptr ? module_list->NumberOfModules : 0UL,
              header->Version);

  UnmapViewOfFile(base);
  CloseHandle(mapping);
  CloseHandle(file);
  return ok ? 0 : 7;
}
