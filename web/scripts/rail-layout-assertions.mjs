import assert from 'node:assert/strict'

// Geometry is shared by all user/admin pages, independent of menu length.
export async function assertFixedRail(page, viewport) {
  const rail = page.getByRole('complementary').first()
  const before = await rail.boundingBox()
  const mobile = viewport.width <= 640
  const expectedWidth = mobile ? viewport.width - 16 : await rail.evaluate(el => parseFloat(getComputedStyle(el).getPropertyValue('--rail-width')))
  assert.equal(await rail.evaluate(el => getComputedStyle(el).position), 'fixed')
  assert.equal(before.x, mobile ? 8 : 12)
  assert.equal(before.y, mobile ? 8 : 12)
  assert.equal(before.width, expectedWidth)
  assert.equal(before.height, mobile ? 60 : viewport.height - 24)
  const main = page.getByRole('main').first()
  const content = await main.boundingBox()
  assert.ok(mobile ? content.y >= 76 : content.x >= before.x + before.width, 'Content reserves space for navigation')
  await main.evaluate(el => {
    for (let parent = el; parent; parent = parent.parentElement) {
      if (parent.scrollHeight > parent.clientHeight) parent.scrollTop = 350
    }
  })
  assert.deepEqual(await rail.boundingBox(), before, 'Navigation stays anchored while content scrolls')
  await main.evaluate(el => { for (let parent = el; parent; parent = parent.parentElement) parent.scrollTop = 0 })
  return before
}
