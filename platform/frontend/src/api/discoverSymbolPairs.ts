/** Browser discovery is a hint; server-side PE/PDB validation is authoritative. */
export interface DiscoveredPair {
  pe: File
  candidates: File[]
  pdbName: string | null
  error: string | null
}

function filePath(file: File): string {
  return (file.webkitRelativePath || file.name).replace(/\\/g, '/')
}

function folder(file: File): string {
  const path = filePath(file)
  return path.slice(0, path.lastIndexOf('/') + 1).toLowerCase()
}

async function read(file: File, offset: number, size: number): Promise<DataView> {
  if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(size) || offset < 0 || size < 0 || size > 1_048_576 || offset + size > file.size) {
    throw new Error('PE 文件结构不完整或超出读取边界')
  }
  return new DataView(await file.slice(offset, offset + size).arrayBuffer())
}

export async function pdbNameFromPe(file: File): Promise<string> {
  const dos = await read(file, 0, 64)
  if (dos.getUint16(0, true) !== 0x5a4d) throw new Error('不是有效 PE 文件')
  const peOffset = dos.getUint32(60, true)
  const header = await read(file, peOffset, 24)
  if (header.getUint32(0, true) !== 0x4550) throw new Error('PE 签名无效')
  if (header.getUint16(4, true) !== 0x8664) throw new Error('当前支持 Windows x64 PE 文件')
  const sectionCount = header.getUint16(6, true)
  const optionalSize = header.getUint16(20, true)
  if (sectionCount === 0 || sectionCount > 96) throw new Error('PE 节表无效')
  const optional = await read(file, peOffset + 24, optionalSize)
  if (optional.byteLength < 168 || optional.getUint16(0, true) !== 0x20b || optional.getUint32(108, true) < 7) {
    throw new Error('需要带调试目录的 Windows x64 PE 文件')
  }
  const debugRva = optional.getUint32(160, true)
  const debugSize = optional.getUint32(164, true)
  if (!debugRva || debugSize < 28 || debugSize % 28 !== 0 || debugSize > 65_536) throw new Error('PE 调试目录缺失或无效')
  const sections = await read(file, peOffset + 24 + optionalSize, sectionCount * 40)
  const offsets: number[] = []
  for (let index = 0; index < sectionCount; index += 1) {
    const start = index * 40
    const rva = sections.getUint32(start + 12, true)
    const rawSize = sections.getUint32(start + 16, true)
    const rawOffset = sections.getUint32(start + 20, true)
    const delta = debugRva - rva
    if (delta >= 0 && delta + debugSize <= rawSize) offsets.push(rawOffset + delta)
  }
  if (offsets.length !== 1) throw new Error('PE 调试目录映射不唯一或缺失')
  const directory = await read(file, offsets[0], debugSize)
  const names = new Set<string>()
  for (let offset = 0; offset < debugSize; offset += 28) {
    if (directory.getUint32(offset + 12, true) !== 2) continue
    const size = directory.getUint32(offset + 16, true)
    if (size < 25 || size > 4096) throw new Error('CodeView 记录长度无效')
    const record = await read(file, directory.getUint32(offset + 24, true), size)
    if (record.getUint32(0, true) !== 0x53445352) throw new Error('需要 RSDS 格式的完整 PDB 引用')
    const bytes = new Uint8Array(record.buffer, 24)
    const end = bytes.indexOf(0)
    if (end < 1) throw new Error('PDB 文件名缺失或无终止符')
    const name = new TextDecoder().decode(bytes.subarray(0, end)).replace(/\\/g, '/').split('/').pop()!
    if (!name.toLowerCase().endsWith('.pdb')) throw new Error('PDB 引用名称无效')
    names.add(name)
  }
  if (names.size !== 1) throw new Error('PDB 引用缺失或存在多个候选')
  return [...names][0]
}

export async function discoverSymbolPairs(files: File[]): Promise<{ pairs: DiscoveredPair[]; ignored: File[] }> {
  const pdbs = files.filter((file) => /\.pdb$/i.test(file.name))
  const pes = files.filter((file) => /\.(dll|exe|sys|ocx)$/i.test(file.name))
  const pairs: DiscoveredPair[] = []
  // Bounded sequential reads avoid loading every selected binary into memory.
  for (const pe of pes) {
    try {
      const pdbName = await pdbNameFromPe(pe)
      const matching = pdbs.filter((file) => file.name.toLowerCase() === pdbName.toLowerCase())
      const local = matching.filter((file) => folder(file) === folder(pe))
      pairs.push({ pe, pdbName, candidates: local.length ? local : matching, error: null })
    } catch (error) {
      pairs.push({ pe, pdbName: null, candidates: [], error: error instanceof Error ? error.message : '无法读取 PE 调试信息' })
    }
  }
  return { pairs, ignored: files.filter((file) => !pes.includes(file) && !pdbs.includes(file)) }
}
