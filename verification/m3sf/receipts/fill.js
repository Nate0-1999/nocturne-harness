// Fill the open deliberation card like an owner: label by label, then sign.
async function fillDeliberation(spec) {
  const f = frame('conversation')
  const card = f.getByTestId('symphony-deliberation').last()
  await card.scrollIntoViewIfNeeded()
  const field = (name) => card.getByLabel(name, { exact: true }).first()
  await field('Desired outcome').fill(spec.outcome)
  await field('Why this deserves a Symphony').fill(spec.why)
  await field('Step 1').fill(spec.step)
  await field('Done when').fill(spec.done)
  await card.getByLabel(/Stratagems/).fill(spec.stratagems.join('\n'))
  const judges = card.locator('.symphony-judge')
  for (const [index, seat] of ['motivation', 'implementation', 'performance'].entries()) {
    const judge = judges.nth(index)
    await judge.getByLabel('Rubric', { exact: true }).fill(spec[seat].rubric)
    await judge.getByLabel('Required evidence', { exact: true }).fill(spec[seat].evidence)
    if (seat === 'performance') await judge.getByLabel('Precalculated metric', { exact: true }).fill(spec.performance.metric)
  }
  for (const [label, value] of Object.entries(spec.walls)) await field(label).fill(String(value))
  await card.locator('.symphony-sign input').check()
  return card
}
