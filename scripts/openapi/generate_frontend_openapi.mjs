import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const repositoryRoot = resolve(scriptDirectory, '../..')
const frontendRoot = resolve(repositoryRoot, 'platform/frontend')
const exporter = resolve(repositoryRoot, 'scripts/openapi/export_platform_openapi.py')
const schemaPath = resolve(frontendRoot, 'openapi.json')
const generatedPath = resolve(frontendRoot, 'src/generated/openapi.ts')
const checkOnly = process.argv.includes('--check')
const requireFromFrontend = createRequire(resolve(frontendRoot, 'package.json'))
const { default: openapiTS, astToString } = requireFromFrontend('openapi-typescript')

function canRun(command) {
  const result = spawnSync(command, ['--version'], { stdio: 'ignore', windowsHide: true })
  return !result.error && result.status === 0
}

function selectPython() {
  const candidates = [
    process.env.PHASE1_PYTHON,
    resolve(repositoryRoot, 'platform/.venv/Scripts/python.exe'),
    resolve(repositoryRoot, 'platform/.venv/bin/python'),
    process.env.PYTHON,
    process.platform === 'win32' ? 'python' : 'python3',
    'python3',
    'python',
  ].filter(Boolean)

  for (const candidate of candidates) {
    if (candidate.includes('/') || candidate.includes('\\')) {
      if (existsSync(candidate) && canRun(candidate)) return candidate
    } else if (canRun(candidate)) {
      return candidate
    }
  }

  throw new Error(
    'Unable to find Python. Set PHASE1_PYTHON or create platform/.venv with the platform dependencies.',
  )
}

function exportSchema() {
  const python = selectPython()
  const argumentsForPython = [exporter, '--output', schemaPath]
  if (checkOnly) argumentsForPython.push('--check')
  const result = spawnSync(python, argumentsForPython, {
    cwd: repositoryRoot,
    stdio: 'inherit',
    windowsHide: true,
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`OpenAPI export failed with exit code ${result.status}`)
}

async function renderTypes() {
  const schema = JSON.parse(readFileSync(schemaPath, 'utf-8'))
  const ast = await openapiTS(schema)
  const rendered = astToString(ast)
  return rendered.endsWith('\n') ? rendered : `${rendered}\n`
}

async function main() {
  exportSchema()
  const expected = await renderTypes()

  if (checkOnly) {
    if (!existsSync(generatedPath)) {
      throw new Error(`Generated OpenAPI types are missing: ${generatedPath}`)
    }
    const current = readFileSync(generatedPath, 'utf-8')
    if (current !== expected) {
      throw new Error('Generated OpenAPI types are stale; run pnpm openapi:generate')
    }
    console.log(`Generated OpenAPI types are current: ${generatedPath}`)
    return
  }

  mkdirSync(dirname(generatedPath), { recursive: true })
  writeFileSync(generatedPath, expected, 'utf-8')
  console.log(`Generated OpenAPI types: ${generatedPath}`)
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error)
  process.exitCode = 1
})
