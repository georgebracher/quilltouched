// Pure Chronicle merge: node --experimental-strip-types --test tests/
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { mergeRecovered, type Ordered } from '../src/chronicle.ts'

const turn = (commandId: string, eventId: number | null): Ordered => ({ kind: 'action', commandId, eventId })
const note: Ordered = { kind: 'note' }
const ids = (list: Ordered[]) => list.map((e) => e.commandId ?? e.kind)

test('a cold cache takes canon order', () => {
  const out = mergeRecovered([], [turn('a', 1), turn('b', 2)], new Map())
  assert.deepEqual(ids(out), ['a', 'b'])
})

test('a turn lost from the cache lands in its place, not at the end', () => {
  const shown = [note, turn('a', null), turn('c', null)]
  const out = mergeRecovered(shown, [turn('a', 1), turn('b', 2), turn('c', 3)], new Map([['a', 1], ['b', 2], ['c', 3]]))
  assert.deepEqual(ids(out), ['note', 'a', 'b', 'c'])
})

test('turns already shown are not added twice', () => {
  const out = mergeRecovered([turn('a', 1)], [turn('a', 1)], new Map([['a', 1]]))
  assert.deepEqual(ids(out), ['a'])
})

test('a turn canon never recorded (unnarrated) is not overtaken: its time is unknown', () => {
  const shown = [turn('a', 1), turn('unnarrated', null)]
  const out = mergeRecovered(shown, [turn('b', 2)], new Map([['a', 1], ['b', 2]]))
  assert.deepEqual(ids(out), ['a', 'unnarrated', 'b'])
})
