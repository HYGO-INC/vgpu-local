import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdir, mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('..', import.meta.url));
const packageFile = require.resolve('@typespec/compiler/package.json');
const compiler = JSON.parse(await readFile(packageFile, 'utf8'));
const check = process.argv.includes('--check');
const tempRoot = resolve(root, '.generated-check');
await mkdir(tempRoot, { recursive: true });
const temp = await mkdtemp(resolve(tempRoot, 'protocol-'));
try {
  execFileSync(process.execPath, [resolve(dirname(packageFile), compiler.bin.tsp),
    'compile', 'protocol', '--output-dir', resolve(temp, 'spec')], { cwd: root, stdio: 'inherit' });
  const api = resolve(temp, 'spec/openapi.json');
  await writeFile(resolve(temp, 'types.ts'), '// Generated; edit protocol/backend.tsp.\n' + astToString(await openapiTS(pathToFileURL(api))));
  execFileSync('uv', ['run', '--locked', 'datamodel-codegen', '--input', api,
    '--input-file-type', 'openapi', '--output', resolve(temp, 'models.py'),
    '--output-model-type', 'pydantic_v2.BaseModel', '--base-class', 'vgpu_local.contracts.base.ContractModel',
    '--target-python-version', '3.12', '--field-constraints', '--enum-field-as-literal', 'all',
    '--collapse-root-models', '--disable-timestamp', '--extra-fields', 'forbid', '--formatters', 'black', 'isort'],
  { cwd: root, stdio: 'inherit' });
  const pairs = [
    ['spec/openapi.json', 'protocol/generated/openapi.json'],
    ['spec/resources.json', 'protocol/generated/resources.json'],
    ['types.ts', 'protocol/generated/types.ts'],
    ['models.py', 'src/vgpu_local/contracts/models.py'],
  ];
  const stale = [];
  for (const [from, to] of pairs) {
    const generated = (await readFile(resolve(temp, from), 'utf8')).replaceAll('\r\n', '\n');
    const destination = resolve(root, to);
    if (check) {
      const actual = await readFile(destination, 'utf8').catch(e => { if (e.code === 'ENOENT') return ''; throw e; });
      if (actual.replaceAll('\r\n', '\n') !== generated) stale.push(to);
    } else {
      await mkdir(dirname(destination), { recursive: true });
      await writeFile(destination, generated);
    }
  }
  if (stale.length) throw new Error(`Generated files differ: ${stale.join(', ')}; run pnpm generate.`);
} finally {
  if (dirname(temp) !== tempRoot) throw new Error('Unexpected temporary path');
  await rm(temp, { recursive: true, force: true });
}
