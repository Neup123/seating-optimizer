import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {tableFitsRoom} from "../../src/seating_optimizer/api/web/room-outline.js";
import {nextFreeTablePosition,renamedTableState} from "../../src/seating_optimizer/api/web/app.js";

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

test("table ID rename rekeys exact table references without rewriting arbitrary prose",()=>{
  const tables=[{id:"T1",zone_id:"hall",capacity:5,name:"Near door"},
                {id:"T2",zone_id:"hall",capacity:6}];
  const layout={floors:[{zone_id:"hall",width:200,height:120,
    tables:[{table_id:"T1",x:0,y:0,width:80,height:80},
            {table_id:"T2",x:100,y:0,width:80,height:80}]}]};
  const rules=[
    {id:"lock",table:"T1",name:"T1 mentioned as label",legacy_source:{parameters:{table:"T1"}}},
    {id:"priority",tiers:[{tables:["T1","T2"],zones:["hall"]}]},
    {id:"pin",shape:"pin",parameters:{table:"T1",attribute:"T1"}}
  ];
  const instructions=[{id:"move",place_type:"table",place_id:"T1",
    guest_tables:{g1:"T1",g2:"T2"}}];
  const snapshot=JSON.stringify({tables,layout,rules,instructions});
  const next=renamedTableState(tables,layout,rules,instructions,"T1","A1");
  assert.equal(next.tables[0].id,"A1");
  assert.equal(next.tables[0].name,"Near door");
  assert.equal(next.layout.floors[0].tables[0].table_id,"A1");
  assert.equal(next.rules[0].table,"A1");
  assert.equal(next.rules[0].legacy_source.parameters.table,"A1");
  assert.deepEqual(next.rules[1].tiers[0].tables,["A1","T2"]);
  assert.equal(next.rules[2].parameters.table,"A1");
  assert.equal(next.rules[2].parameters.attribute,"T1");
  assert.equal(next.rules[0].name,"T1 mentioned as label");
  assert.equal(next.instructions[0].place_id,"A1");
  assert.deepEqual(next.instructions[0].guest_tables,{g1:"A1",g2:"T2"});
  assert.equal(JSON.stringify({tables,layout,rules,instructions}),snapshot,"original inputs must not mutate");
  assert.throws(()=>renamedTableState(tables,layout,rules,instructions,"T1","T2"),/unique/);
});
