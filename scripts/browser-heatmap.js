async (page) => {
  const check = (value, message) => { if (!value) throw Error(message) }
  const errors = []
  let intentionalFailure = false
  page.on("console", m => { if (m.type() === "error" && !(intentionalFailure && m.text().includes("500"))) errors.push(m.text()) })
  page.on('pageerror', e => errors.push(e.message))
  await page.setViewportSize({width:1440,height:1080})
  await page.goto('http://127.0.0.1:8765')
  await page.getByLabel('Исследование',{exact:true}).selectOption('cnrpark-day')
  await page.locator('.heatmap-layer[data-ready="true"]').waitFor()
  check(await page.getByLabel('Непрозрачность карты',{exact:true}).inputValue()==='0.7','Shared default opacity mismatch')
  await page.evaluate(() => document.fonts.ready)
  check(await page.locator('.parking-overlay').count() === 0, 'Old polygon heatmap is still visible')
  const initial = await (await page.request.get('http://127.0.0.1:8765/api/projects/cnrpark-day')).json()
  const values = await page.locator('.thermal-canvas').evaluate(c => {
    const pixels=c.getContext('2d').getImageData(0,0,c.width,c.height).data
    let hot=0,cold=0,solid=0,support=0
    for(let i=0;i<pixels.length;i+=4) if(pixels[i+3]>80) {
      support++
      if(pixels[i+3]>=230) solid++
      if(pixels[i]>pixels[i+2]+50) hot++
      if(pixels[i+2]>pixels[i]+40) cold++
    }
    return {hot,cold,solidFraction:solid/support}
  })
  check(values.hot>100 && values.cold>100,'Real thermal field lacks expected hot/cold data')
  check(values.solidFraction>.55,'Color core is too small or washed out')
  const legendColors = await page.locator('.heat-scale').evaluate(el => [...el.style.background.matchAll(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/g)].map(m=>m.slice(1).map(Number)))
  check(legendColors.length===101,'Legend must use the full hue-preserving ramp')
  await page.getByLabel('Позиция видео',{exact:true}).fill('18')
  await page.waitForFunction(() => !document.querySelector('video').seeking)
  check(await page.locator('.playback-time').textContent()==='11:58','Source timestamp mismatch')
  const slot=page.locator('[data-heat-slot="613"]')
  await slot.click()
  check(await slot.evaluate(el => getComputedStyle(el).outlineStyle === 'none'),'Visible ROI focus rectangle')
  check(await page.locator('.heat-tooltip > strong').textContent()==='Место 613','Selected place card missing')
  const summary=await (await page.request.get('http://127.0.0.1:8765/api/runs/'+initial.completed_run_id+'/summary')).json()
  const actual=summary.slots.find(s=>s.id==='613')
  check(await page.locator('.heat-tooltip-value').textContent()===Math.round(actual.occupancy)+'%','Card changed measured occupancy')
  await page.getByLabel('Непрозрачность карты',{exact:true}).fill('0')
  check(await page.locator('.thermal-canvas').evaluate(c=>getComputedStyle(c).opacity)==='0','Opacity slider failed')
  check(await page.locator('.heat-tooltip-value').textContent()===Math.round(actual.occupancy)+'%','Opacity changed values')
  await page.getByLabel('Непрозрачность карты',{exact:true}).fill('0.7')
  await slot.focus()
  await page.keyboard.press('ArrowRight')
  check(await page.locator('.heat-tooltip > strong').textContent()==='Место 614','Map arrow navigation failed')
  await page.keyboard.press('Escape')
  check(await page.locator('.heat-tooltip').count()===0,'Escape did not dismiss card')
  await page.getByLabel('Палитра карты',{exact:true}).selectOption('warm')
  await page.locator('.heatmap-layer[data-ready="true"]').waitFor()
  check(await page.locator('.heat-scale').evaluate(el=>getComputedStyle(el).background).then(s=>s.includes('255, 242, 163')),'Legend is not using shared warm palette')
  await page.getByLabel('Палитра карты',{exact:true}).selectOption('thermal')
  await page.locator('.heatmap-layer[data-ready="true"]').waitFor()
  await page.getByLabel('Конец интервала',{exact:true}).fill('9180')
  await page.locator('.heatmap-layer[data-ready="true"]').waitFor()
  check(await page.locator('.heat-period').textContent().then(s=>s.includes('09:55')),'Selected interval not shown')
  await page.getByRole('button',{name:'Весь день',exact:true}).click()
  await page.locator('.heatmap-layer[data-ready="true"]').waitFor()
  for (const [name,ext] of [['Карта PNG','png'],['CSV','csv'],['Видео MP4','mp4']]) {
    const [download]=await Promise.all([page.waitForEvent('download',{timeout:120000}), page.getByRole('button',{name,exact:true}).click()])
    await download.saveAs('artifacts/thermal-final.'+ext)
    if(await page.locator('.alert.success .icon-button').count()) await page.locator('.alert.success .icon-button').click()
  }
  await page.getByRole('button',{name:'Развернуть видео'}).click()
  const alignment=await page.evaluate(()=>{
    const v=document.querySelector('video').getBoundingClientRect(),c=document.querySelector('.thermal-canvas').getBoundingClientRect()
    return {dx:Math.abs(v.x-c.x),dy:Math.abs(v.y-c.y),dw:Math.abs(v.width-c.width),dh:Math.abs(v.height-c.height)}
  })
  check(Object.values(alignment).every(n=>n<1),'Fullscreen field misalignment')
  await page.getByRole('button',{name:'Свернуть видео'}).click()
  await page.waitForFunction(()=>!document.fullscreenElement)
  await page.getByRole('button',{name:'Занятость',exact:true}).click()
  check(await page.locator('.parking-overlay').count()===1,'Frame-state overlay missing')
  await page.locator('[data-cell="0-0"]').click()
  check(await page.locator('video').evaluate(v=>Math.abs(v.currentTime)<.1),'Matrix seek failed')
  await page.getByRole('button',{name:'Разметка',exact:true}).click()
  check(await page.locator('.parking-overlay .slot-group').count()===54,'Editor ROIs lost')
  await page.getByRole('button',{name:'Обзор',exact:true}).click()
  await page.getByRole('button',{name:'Тепловая карта',exact:true}).click()
  await page.locator('.heatmap-layer[data-ready="true"]').waitFor()
  intentionalFailure = true
  await page.route('**/heatmap.png?**',route=>route.fulfill({status:500,body:'test failure'}),{times:1})
  await page.getByLabel('Палитра карты',{exact:true}).selectOption('warm')
  await page.getByText('Не удалось построить тепловой слой.',{exact:false}).waitFor()
  await page.getByRole('button',{name:'Повторить',exact:true}).click()
  await page.locator('.heatmap-layer[data-ready="true"]').waitFor()
  intentionalFailure = false
  await page.getByLabel('Палитра карты',{exact:true}).selectOption('thermal')
  await page.locator('.heatmap-layer[data-ready="true"]').waitFor()
  await page.getByLabel('Позиция видео',{exact:true}).fill('18')
  await page.waitForFunction(()=>!document.querySelector('video').seeking)
  await slot.click()
  await page.evaluate(()=>window.scrollTo(0,0))
  await page.screenshot({path:'artifacts/thermal-desktop.png',fullPage:true})
  await page.locator('.video-column').screenshot({path:'artifacts/thermal-map.png'})
  await page.setViewportSize({width:390,height:844})
  await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth)
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile page overflow')
  const mobile=await page.locator('.heat-tooltip').evaluate(el=>{
    const card=el.getBoundingClientRect(),map=el.closest('.video-plane').getBoundingClientRect()
    return {inside:card.top>=map.top && card.bottom<=map.bottom && card.left>=map.left && card.right<=map.right,close:el.querySelector('button').getBoundingClientRect().height}
  })
  check(mobile.inside && mobile.close>=44,'Mobile card clipping or small touch target')
  const expand = page.getByRole('button',{name:'Развернуть видео'})
  check(await expand.isVisible(),'Mobile fullscreen control is hidden')
  check((await expand.boundingBox()).height >= 44,'Mobile fullscreen touch target is too small')
  await expand.click()
  await page.waitForFunction(() => !!document.fullscreenElement)
  await page.getByRole('button',{name:'Свернуть видео'}).click()
  await page.waitForFunction(() => !document.fullscreenElement)
  await page.screenshot({path:'artifacts/thermal-mobile.png',fullPage:true})
  await page.emulateMedia({reducedMotion:'reduce'})
  const final=await(await page.request.get('http://127.0.0.1:8765/api/projects/cnrpark-day')).json()
  check(final.latest_run.id===initial.latest_run.id,'Visual controls reran the model')
  check(errors.length===0,errors.join(';'))
  return {passed:true,values,legendColors,alignment,mobile,browserErrors:errors,scenarios:['broad saturated field','opacity preserves measurements','hue-preserving palette and legend','card and keyboard','source clock','time interval','PNG/CSV/MP4','fullscreen','state overlay','editor','matrix','handled retry','mobile','reduced motion']}
}
