import { readFileSync } from 'node:fs';

const project = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const expectedNode = project.engines.node;
const expectedNpm = project.engines.npm;
const nvmrc = readFileSync(new URL('../.nvmrc', import.meta.url), 'utf8').trim();

if (nvmrc !== expectedNode || project.packageManager !== `npm@${expectedNpm}`) {
  console.error('Control Plane Node/npm declarations disagree with package.json');
  process.exit(2);
}

if (process.version !== `v${expectedNode}`) {
  console.error(`Control Plane requires Node ${expectedNode}, got ${process.version}`);
  process.exit(2);
}

const userAgent = process.env.npm_config_user_agent ?? '';
if (!userAgent.startsWith(`npm/${expectedNpm}`)) {
  console.error(`Control Plane requires npm/${expectedNpm}, got ${userAgent || 'unknown npm'}`);
  process.exit(2);
}
