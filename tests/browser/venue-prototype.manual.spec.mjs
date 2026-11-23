import { test, expect } from '@playwright/test';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { mkdirSync } from 'node:fs';

const url = pathToFileURL(resolve('prototypes/venue-editor-121-123.html')).href;
const output = 'test-results/venue-prototype';
mkdirSync(output, { recursive: true });
const shot = async (page, name) => page.screenshot({path: output + '/' + name + '.png', fullPage: true, animations: 'disabled'});
const field = (page, name) => page.locator('#editor label').filter({hasText: name}).locator('input').first();

test('operator click review: tables, keyboard, resize, room outline, removal', async ({browser}) => {
  const context = await browser.newContext({viewport:{width:1600,height:1000},deviceScaleFactor:2});
  const page = await context.newPage();
  const errors=[], dialogs=[];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', async dialog => {dialogs.push(dialog.message());await dialog.accept();});
  await page.goto(url);
  await expect(page.locator('#stats')).toHaveText('5 tables · 48 chairs');
  await shot(page,'01-initial');
  await page.getByRole('button',{name:/Add table/}).click();
  await expect(page.locator('#stats')).toHaveText('6 tables · 58 chairs');
  // Default placement must never produce an overlapping table, including
  // the round table's bounding geometry. Production has the same safety goal.
  const overlaps = await page.locator('#canvas').evaluate(svg => {
    const boxes=[...svg.querySelectorAll('g.table-entity .shape')].map(el => {
      const b=el.getBBox();return{x:b.x,y:b.y,w:b.width,h:b.height};
    });
    const collisions=[];
    for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
      const a=boxes[i],b=boxes[j];
      if(a.x < b.x+b.w && a.x+a.w>b.x && a.y<b.y+b.h && a.y+a.h>b.y)collisions.push([i,j]);
    }
    return collisions;
  });
  expect(overlaps,'Adding a table must not overlap an existing table').toEqual([]);

  await expect(page.locator('#editor h3')).toHaveText('Edit T6');
  const name = field(page,'Display name');
  await name.fill('Operator Test Banquet');
  await name.press('Tab');
  await expect(page.locator('#list')).toContainText('Operator Test Banquet');
  const id = field(page,'Table ID');
  await id.fill('T1');
  await id.press('Tab');
  await expect(page.locator('#toast')).toContainText('ID must be unique');
  await expect(page.locator('#editor h3')).toHaveText('Edit T6');
  await page.locator('#search').fill('operator test');
  await expect(page.locator('#list .table-row')).toHaveCount(1);
  await page.locator('#search').fill('');
  await expect(page.locator('#list .table-row')).toHaveCount(6);
  let table=page.locator('#canvas g[data-id="T6"]');
  const x=Number(await table.locator('rect.shape').getAttribute('x'));
  await table.focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(async()=>Number(await page.locator('#canvas g[data-id="T6"] rect.shape').getAttribute('x'))).toBe(x+5);
  const handle=page.locator('#canvas g[data-id="T6"] rect.resize');
  const width=Number(await page.locator('#canvas g[data-id="T6"] rect.shape').getAttribute('width'));
  const box=await handle.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+32,box.y+box.height/2+20,{steps:8});
  await page.mouse.up();
  expect(Number(await page.locator('#canvas g[data-id="T6"] rect.shape').getAttribute('width'))).toBeGreaterThan(width);
  await shot(page,'02-edited-table');
  await page.getByRole('button',{name:'Edit room outline'}).click();
  const canvas=page.locator('#canvas'),bounds=await canvas.boundingBox();
  expect(bounds).not.toBeNull();
  await canvas.click({position:{x:bounds.width*.15,y:bounds.height*.15}});
  await canvas.click({position:{x:bounds.width*.8,y:bounds.height*.15}});
  await canvas.click({position:{x:bounds.width*.75,y:bounds.height*.8}});
  await page.getByRole('button',{name:'Save outline'}).click();
  await expect(page.locator('#toast')).toContainText('contain every table');
  await expect(page.getByRole('button',{name:'Save outline'})).toBeVisible();
  await page.getByRole('button',{name:'Edit room outline'}).click();
  for(const [x,y] of [[.035,.07],[.96,.07],[.96,.93],[.035,.93]]){
    await canvas.click({position:{x:bounds.width*x,y:bounds.height*y}});
  }
  await page.getByRole('button',{name:'Save outline'}).click();
  await expect(page.locator('#toast')).toContainText('Room outline saved');
  await shot(page,'03-room-outline');
  await page.getByRole('button',{name:'Reset outline'}).click();
  await expect(page.locator('#canvas polygon.room')).toHaveAttribute('points',/50,50 710,50/);
  await page.getByRole('button',{name:'Remove table'}).click();
  await expect(page.locator('#stats')).toHaveText('5 tables · 48 chairs');
  expect(dialogs.some(x=>x.includes('Operator Test Banquet'))).toBe(true);
  expect(errors).toEqual([]);
  await shot(page,'04-after-remove');
  await context.close();
});

test('mobile review: no horizontal overflow and usable add flow', async ({browser}) => {
  const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:2,isMobile:true,hasTouch:true});
  const page=await context.newPage();
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);
  await expect(page.locator('#stats')).toHaveText('5 tables · 48 chairs');
  await expect(page.locator('#canvas')).toBeVisible();
  await shot(page,'05-mobile-initial');
  const dims=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));
  expect(dims.scrollWidth,JSON.stringify(dims)).toBeLessThanOrEqual(dims.width+2);
  await page.getByRole('button',{name:/Add table/}).click();
  await expect(page.locator('#stats')).toContainText('6 tables');
  await expect(page.locator('#editor-name')).toBeFocused();
  await shot(page,'06-mobile-add');
  expect(errors).toEqual([]);
  await context.close();
});
