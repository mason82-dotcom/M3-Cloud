import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.10.0/dist/maplibre-gl.mjs';

const API='/api/v1';
const state={vehicles:[],map:null,markers:new Map(),selectedVehicleId:null};
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
function normalizeVehicle(v){
 const t=v.telemetry||{}; const p=t.payload||{}; const b=t.battery||{};
 return {raw:v,id:v.id||v.sn||v.device_sn||'unknown',name:v.name||v.callsign||v.model||'Aircraft',model:v.model||v.product||p.platform||'DJI',source:v.source||'unknown',online:v.online!==false,lat:Number(v.lat??v.latitude??t.latitude),lng:Number(v.lng??v.longitude??t.longitude),alt:v.alt??v.altitude??t.relative_altitude_m,amsl:t.amsl_altitude_m,rtk:v.rtk||v.rtk_status||t.rtk?.fix||'—',battery:v.battery??v.battery_percent??b.capacity_percent,sats:v.satellites??v.gps_satellites??t.gps_satellites,payload:p,lrf:t.lrf||{},camera:t.camera||{}}
}
function esc(v){return String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function payloadCards(v){
 const p=v.payload||{}, cam=p.camera||{}, platform=String(p.platform||v.model||'UNKNOWN').toUpperCase();
 const common=`<div class="payloadCard"><h3>Camera identity</h3><dl><dt>Platform</dt><dd>${esc(platform)}</dd><dt>MSDK CameraType</dt><dd>${esc(cam.camera_type)}</dd><dt>Firmware</dt><dd>${esc(cam.firmware_version)}</dd><dt>Mode</dt><dd>${esc(cam.camera_mode)}</dd><dt>Live source</dt><dd>${esc(cam.live_view_source)}</dd></dl></div>`;
 if(platform==='M3E') return common+`<div class="payloadCard accentE"><h3>M3E Mapping</h3><p>RGB mapping payload</p><div class="chips"><span>Wide</span><span>Zoom</span><span>M3E_MAPPING</span></div><dl><dt>Stored sources</dt><dd>${esc((cam.capture_stored_sources||[]).join(', ')||'—')}</dd></dl></div>`;
 if(platform==='M3T') return common+`<div class="payloadCard accentT"><h3>M3T Thermal / LRF</h3><p>Visual, thermal and ranging payload</p><div class="chips"><span>Wide</span><span>Zoom</span><span>Thermal</span><span>LRF</span></div><dl><dt>LRF distance</dt><dd>${v.lrf.distance_m==null?'—':esc(v.lrf.distance_m)+' m'}</dd><dt>Thermal capture</dt><dd>${p.thermal?'available':'not reported'}</dd></dl></div>`;
 if(platform==='M3M') return common+`<div class="payloadCard accentM"><h3>M3M Multispectral</h3><p>RGB + multispectral capture</p><div class="chips"><span>RGB</span><span>Green</span><span>Red</span><span>Red Edge</span><span>NIR</span></div><dl><dt>Capture profile</dt><dd>M3M_RGB_MULTISPECTRAL</dd><dt>Stored sources</dt><dd>${esc((cam.capture_stored_sources||[]).join(', ')||'—')}</dd></dl></div>`;
 return common+`<div class="payloadCard"><h3>Unclassified payload</h3><p>Keine eindeutige MSDK CameraType-Identität. Funktionen werden nicht aus hasThermal oder anderen Indizien abgeleitet.</p></div>`;
}
function renderPayload(vs){
 let v=vs.find(x=>x.id===state.selectedVehicleId);
 if(!v&&vs.length){v=vs[0];state.selectedVehicleId=v.id}
 if(!v){$('#payloadPlatform').textContent='UNKNOWN';$('#payloadSubtitle').textContent='Aircraft auswählen';$('#payloadBody').className='empty';$('#payloadBody').textContent='Ein Aircraft in der Fleet auswählen, um Payload-Daten anzuzeigen.';return}
 $('#payloadPlatform').textContent=v.payload?.platform||v.model||'UNKNOWN';$('#payloadSubtitle').textContent=v.name+' · '+v.source;$('#payloadBody').className='payloadBody';$('#payloadBody').innerHTML=payloadCards(v);
}
function render(){
 const vs=state.vehicles.map(normalizeVehicle);
 $('#aircraftCount').textContent=vs.length; $('#onlineCount').textContent=vs.filter(v=>v.online).length;
 $('#rtkCount').textContent=vs.filter(v=>String(v.rtk).toUpperCase().includes('FIX')).length; $('#fleetState').textContent=vs.length+' devices';
 $('#aircraftHint').textContent=vs.length?'telemetry active':'keine Telemetrie';
 $('#fleetList').innerHTML=vs.length?vs.map(v=>`<article class="fleetItem ${v.id===state.selectedVehicleId?'selected':''}" data-vehicle-id="${esc(v.id)}"><div class="row"><div><strong>${v.name}</strong><small>${v.model} · ${v.source}</small></div><span class="badge ${String(v.rtk).toUpperCase().includes('FIX')?'fix':''}">${n(v.rtk)}</span></div><div class="telemetry"><span>Battery<b>${n(v.battery)}${v.battery!=null?'%':''}</b></span><span>Altitude<b>${n(v.alt)}${v.alt!=null?' m':''}</b></span><span>Satellites<b>${n(v.sats)}</b></span></div></article>`).join(''):'<div class="empty">Noch keine Aircraft-Telemetrie vom Backend.</div>';
 document.querySelectorAll('.fleetItem[data-vehicle-id]').forEach(el=>el.addEventListener('click',()=>{state.selectedVehicleId=el.dataset.vehicleId;render()}));
 renderPayload(vs);
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
