import test from 'node:test'
import assert from 'node:assert/strict'

import { describeVoiceWorkflowError } from './voiceWorkflowError.js'

test('describes dataset failures separately from service failures', () => {
  const result = describeVoiceWorkflowError({
    response: {
      status: 422,
      data: {
        category: 'data_source',
        code: 'dataset_metadata_missing',
        message: 'Workspace 2 has no uploaded dataset.',
      },
    },
  })

  assert.equal(result.category, 'data_source')
  assert.equal(result.message, 'Data source: Workspace 2 has no uploaded dataset.')
  assert.equal(result.shouldShowSubscription, false)
})

test('recognizes subscription-limit responses', () => {
  const result = describeVoiceWorkflowError({
    response: {
      status: 403,
      data: { message: 'You have reached your limit. Please subscribe.' },
    },
  })

  assert.equal(result.category, 'subscription')
  assert.equal(result.shouldShowSubscription, true)
})
