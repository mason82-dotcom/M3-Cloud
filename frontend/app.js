import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.10.0/dist/maplibre-gl.mjs';

const API='/api/v1';
const state={vehicles:[],map:null,markers:new Map()};
const $=(s)=>document.querySelector(s);
const texts={
 fleet:['Fleet','Aircraft, Payloads, RTK und Verbindungsstatus.'],
 missions:['Missions','Waylines, Missionsplanung, Preflight und Ausführungsstatus.'],
 live:['Live','Liveview und Telemetrie für DJI Cloud API und Lyrebird.'],
 media:['Media','Fotos, Videos, Thermal- und Multispektraldaten.'],
 processing:['Processing','Photogrammetrie, Thermogram und weitere Processing-Pipelines.'],
 system:['System','EMQX, PostgreSQL, MinIO, Backend und Integrationen.']
};

function initMap(){
 try{
  state.map=new maplibregl.Map({container:'map',style:{version:8,sources:{osm:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,attribution:'© OpenStreetMap contributors'}},layers:[{id:'osm',type:'raster',source:'osm'}]},center:[8.58,49.12],zoom:9});
  state.map.addControl(new maplibregl.NavigationControl({showCompass:true}),'top-right');
  state.map.on('error',()=>{});
 }catch(e){$('#mapFallback').hidden=false}
}
function n(v,d='—'){return v===null||v===undefined?d:v}
function normalizeVehicle(v){return {id:v.id||v.sn||v.device_sn||'unknown',name:v.name||v.callsign||v.model||'Aircraft',model:v.model||v.product||'DJI',source:v.source||'unknown',online:v.online!==false,lat:Number(v.lat??v.latitude),lng:Number(v.lng??v.longitude),alt:v.alt??v.altitude,rtk:v.rtk||v.rtk_status||'—',battery:v.battery??v.battery_percent,sats:v.satellites??v.gps_satellites}}
function render(){
 const vs=state.vehicles.map(normalizeVehicle);
 $('#aircraftCount').textContent=vs.length; $('#onlineCount').textContent=vs.filter(v=>v.online).length;
 $('#rtkCount').textContent=vs.filter(v=>String(v.rtk).toUpperCase().includes('FIX')).length; $('#fleetState').textContent=vs.length+' devices';
 $('#aircraftHint').textContent=vs.length?'telemetry active':'keine Telemetrie';
 $('#fleetList').innerHTML=vs.length?vs.map(v=>`<article class="fleetItem"><div class="row"><div><strong>${v.name}</strong><small>${v.model} · ${v.source}</small></div><span class="badge ${String(v.rtk).toUpperCase().includes('FIX')?'fix':''}">${n(v.rtk)}</span></div><div class="telemetry"><span>Battery<b>${n(v.battery)}${v.battery!=null?'%':''}</b></span><span>Altitude<b>${n(v.alt)}${v.alt!=null?' m':''}</b></span><span>Satellites<b>${n(v.sats)}</b></span></div></article>`).join(''):'<div class="empty">Noch keine Aircraft-Telemetrie vom Backend.</div>';
 updateMarkers(vs);
}
function updateMarkers(vs){
 if(!state.map)return;
 const alive=new Set();
 vs.filter(v=>Number.isFinite(v.lat)&&Number.isFinite(v.lng)).forEach(v=>{alive.add(v.id);let m=state.markers.get(v.id);if(!m){const el=document.createElement('div');el.style.cssText='width:14px;height:14px;border-radius:50%;background:#4fc3b6;border:2px solid white;box-shadow:0 0 0 4px #4fc3b633';m=new maplibregl.Marker({element:el}).setLngLat([v.lng,v.lat]).setPopup(new maplibregl.Popup({offset:12}).setText(v.name)).addTo(state.map);state.markers.set(v.id,m)}else m.setLngLat([v.lng,v.lat])});
 for(const [id,m] of state.markers)if(!alive.has(id)){m.remove();state.markers.delete(id)}
}
async function getJson(url){const r=await fetch(url,{headers:{accept:'application/json'}});if(!r.ok)throw new Error(r.status);return r.json()}
async function refresh(){
 try{
  const health=await getJson(API+'/system/health'); $('#apiStatus').textContent='Backend online'; $('#apiStatus').className='status good';
  const comps=health.components||health.services||{}; for(const [id,key] of [['djiState','dji'],['lyrebirdState','lyrebird'],['mqttState','mqtt'],['storageState','storage']]){const el=$('#'+id);const val=comps[key];el.textContent=val?.status||val||'online';el.style.color='#55d58a'}
 }catch(e){$('#apiStatus').textContent='Backend wartet';$('#apiStatus').className='status warn'}
 try{const data=await getJson(API+'/vehicles');state.vehicles=Array.isArray(data)?data:(data.items||data.vehicles||[])}catch(e){state.vehicles=[]}
 render();
}
document.querySelectorAll('.navItem').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.navItem').forEach(x=>x.classList.remove('active'));b.classList.add('active');const v=b.dataset.view;if(v==='operations'){$('#operations').classList.add('active');$('#genericView').classList.remove('active');$('#viewTitle').textContent='Operations';$('#viewSubtitle').textContent='Fleet, RTK und Missionen im Überblick';setTimeout(()=>state.map?.resize(),0)}else{$('#operations').classList.remove('active');$('#genericView').classList.add('active');$('#genericTitle').textContent=texts[v][0];$('#genericText').textContent=texts[v][1];$('#viewTitle').textContent=texts[v][0];$('#viewSubtitle').textContent=texts[v][1]}}));
$('#refreshBtn').addEventListener('click',refresh);
initMap(); refresh(); setInterval(refresh,5000);
