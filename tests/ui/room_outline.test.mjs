import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {tableFitsRoom} from "../../src/seating_optimizer/api/web/room-outline.js";
import {nextFreeTablePosition} from "../../src/seating_optimizer/api/web/app.js";

const cases=JSON.parse(readFileSync(new URL("../fixtures/room_geometry.json",import.meta.url),"utf-8"));

test("room preview matches backend room-polygon acceptance fixtures",()=>{
  for(const item of cases){
    assert.equal(tableFitsRoom(item.outline,...item.rect),item.fits,item.case);
  }
});

test("auto placement never puts a table inside a concave missing-corner area",()=>{
  const outline=[[0,0],[100,0],[100,40],[40,40],[40,100],[0,100]];
  const floor={width:100,height:100,room_outline:outline,tables:[]};
  for(let i=0;i<3;i++){
    const position=nextFreeTablePosition(floor,20,20,4);
    assert.ok(position,"must find a valid free location");
    assert.ok(tableFitsRoom(outline,position.x,position.y,20,20));
    floor.tables.push({table_id:"T"+i,...position,width:20,height:20});
  }
});
