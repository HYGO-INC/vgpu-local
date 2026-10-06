const fs = require('node:fs');
const path = require('node:path');
const Ajv = require('ajv/dist/2020').default;
const ajv = new Ajv({ strict: true, allErrors: true });
ajv.addSchema(require('./generated/resources.json'));
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures.json'), 'utf8'));
process.stdout.write(JSON.stringify(cases.map(item => {
  const validate = ajv.getSchema(`${item.contract}.json`);
  if (!validate) throw new Error(`Missing contract ${item.contract}`);
  return validate(item.document);
})));
