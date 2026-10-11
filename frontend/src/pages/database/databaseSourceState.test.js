import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildInitialConfiguration,
  capabilityConnectorIds,
  connectorWorkflow,
  isSupportedLegacyUpload,
  operationState,
  pollOutcome,
  redactTransientSecrets,
  sourceErrorMessage,
  tableSelectionKey,
} from './databaseSourceState.js'

test('dynamic connector defaults drive the form', () => {
  const connector = { fields: [
    { name: 'host', required: true },
    { name: 'port', default: 5432 },
    { name: 'sslmode', default: 'require' },
  ] }
  assert.deepEqual(buildInitialConfiguration(connector), { port: 5432, sslmode: 'require' })
})

test('password and private key material are cleared after snapshot start', () => {
  const original = { host: 'db.example', password: 'secret', ssl_key: 'pem', username: 'reader' }
  assert.deepEqual(redactTransientSecrets(original), {
    host: 'db.example', password: '', ssl_key: '', username: 'reader',
  })
  assert.equal(original.password, 'secret')
})

test('schema-qualified selections do not collide', () => {
  assert.notEqual(tableSelectionKey({ schema: 'sales', name: 'order' }), tableSelectionKey({ schema: 'hr', name: 'order' }))
})

test('safe connector errors are actionable', () => {
  const error = { response: { data: { error: { code: 'TLS_ERROR', message: 'TLS validation failed.' } } } }
  assert.equal(sourceErrorMessage(error, 'failed'), 'TLS validation failed.')
  assert.equal(sourceErrorMessage({}, 'failed'), 'failed')
})

test('supported connectors are rendered from backend capabilities', () => {
  const ids = capabilityConnectorIds({ connectors: [
    { id: 'postgres' }, { id: 'mysql' }, { id: 'sqlite' }, { id: 'clickhouse' },
  ] })
  assert.deepEqual(ids, ['postgres', 'mysql', 'sqlite', 'clickhouse'])
})

test('database selection switches between server and SQLite workflows', () => {
  assert.equal(connectorWorkflow({ id: 'postgres', workflow: 'server' }), 'server-connection')
  assert.equal(connectorWorkflow({ id: 'sqlite', workflow: 'file_upload' }), 'sqlite-upload')
})

test('test connection exposes success and failure states', () => {
  assert.equal(operationState('test', 'pending'), 'testing')
  assert.equal(operationState('test', 'success'), 'test-success')
  assert.equal(operationState('test', 'failure'), 'failed')
})

test('discovery and snapshot operations expose ready and started states', () => {
  assert.equal(operationState('discover', 'pending'), 'discovering')
  assert.equal(operationState('discover', 'success'), 'ready')
  assert.equal(operationState('snapshot', 'pending'), 'starting')
  assert.equal(operationState('snapshot', 'success'), 'started')
  assert.equal(operationState('snapshot', 'failure'), 'failed')
})

test('polling continues, loads preview on completion, and stops on failure', () => {
  assert.deepEqual(pollOutcome('processing'), { stop: false, loadPreview: false, failed: false })
  assert.deepEqual(pollOutcome('completed'), { stop: true, loadPreview: true, failed: false })
  assert.deepEqual(pollOutcome('failed'), { stop: true, loadPreview: false, failed: true })
})

test('existing CSV and Excel upload workflow remains accepted', () => {
  assert.equal(isSupportedLegacyUpload({ name: 'sales.csv', type: '' }), true)
  assert.equal(isSupportedLegacyUpload({ name: 'sales.xlsx', type: 'application/octet-stream' }), true)
  assert.equal(isSupportedLegacyUpload({ name: 'sales.xls', type: 'application/vnd.ms-excel' }), true)
  assert.equal(isSupportedLegacyUpload({ name: 'sales.exe', type: 'application/octet-stream' }), false)
})
