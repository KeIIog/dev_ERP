let TOKEN = localStorage.getItem('deverp_token') || '';
let USER = JSON.parse(localStorage.getItem('deverp_user') || 'null');
let selectedOrderId = null;
let selectedOrder = null;
let selectedReceiptIds = new Set();
let receiptRows = [];
// 입고 관리: 구매의뢰서 번호별 폴더 트리 펼침 상태
let receiptExpandedGroups = new Set();
let parsedVendors = [];
let parsedEstimateFiles = [];
let currentRequestId = null;
let dashboardOrders = [];
let dashboardFilter = 'all';

const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => Array.from(root.querySelectorAll(s));

function authHeaders(json=true){
  const h = {};
  if (TOKEN) h.Authorization = `Bearer ${TOKEN}`;
  if (json) h['Content-Type'] = 'application/json';
  return h;
}
async function deverpReadResponseJsonOrText(res){
  const raw = await res.text();
  if(!raw) return null;
  try{ return JSON.parse(raw); }catch(e){ return raw; }
}
function deverpResponseMessage(parsed, fallback=''){
  if(parsed == null) return fallback;
  if(typeof parsed === 'string') return parsed || fallback;
  return parsed.detail || parsed.message || JSON.stringify(parsed) || fallback;
}
async function apiFetch(url, opts={}){
  opts.headers = Object.assign({}, opts.headers || {}, authHeaders(!(opts.body instanceof FormData)));
  const res = await fetch(url, opts);
  const parsed = await deverpReadResponseJsonOrText(res);
  if (!res.ok){
    throw new Error(deverpResponseMessage(parsed, `HTTP ${res.status}`));
  }
  return parsed;
}

function showApp(){
  $('#login-screen').classList.add('hidden');
  $('#app').classList.remove('hidden');
  setTimeout(()=>deverpEnsureFixedClientAgentPanel(), 0);
  $('#profile-name').value = USER?.name || USER?.username || '';
  $('#profile-role').value = roleLabel(USER?.role || '');
  $('#pr-requester').value = USER?.name || '';
  $('#pr-department').value = USER?.department || '';
  applyRoleMenu();
  navigate('dashboard');
}
function showLogin(){ $('#app').classList.add('hidden'); $('#login-screen').classList.remove('hidden'); }
function roleLabel(role){ return {admin:'관리자',dev:'개발그룹',purchase:'구매그룹',general:'일반사용자',quality:'품질팀',manufacture:'생산팀'}[role] || role || ''; }
function applyRoleMenu(){
  const role = USER?.role || 'general';
  const allowed = new Set(['dashboard','receipt','settings']);
  if(role === 'dev') allowed.add('purchase');
  if(role === 'purchase') allowed.add('orders');
  if(role === 'admin') ['dashboard','purchase','orders','receipt','settings'].forEach(x=>allowed.add(x));
  $$('.nav-item').forEach(b => b.style.display = allowed.has(b.dataset.page) ? '' : 'none');
  // 위험 작업 버튼은 관리자에게만 노출한다.
  ['delete-order','receipt-delete-btn'].forEach(id=>{ const el = $('#'+id); if(el) el.style.display = (role === 'admin') ? '' : 'none'; });
}

$('#login-form').addEventListener('submit', async e=>{
  e.preventDefault();
  const fd = new URLSearchParams();
  fd.append('username', $('#login-id').value.trim());
  fd.append('password', $('#login-pw').value);
  try{
    const res = await fetch('/api/users/login', {method:'POST', body:fd, headers:{'Content-Type':'application/x-www-form-urlencoded'}});
    if(!res.ok){ const j=await res.json().catch(()=>({})); throw new Error(j.detail || '로그인 실패'); }
    const data = await res.json();
    TOKEN = data.access_token; USER = data;
    localStorage.setItem('deverp_token', TOKEN);
    localStorage.setItem('deverp_user', JSON.stringify(USER));
    showApp();
  }catch(err){ $('#login-msg').textContent = err.message; }
});
$('#logout').onclick = ()=>{ localStorage.removeItem('deverp_token'); localStorage.removeItem('deverp_user'); TOKEN=''; USER=null; showLogin(); };

function navigate(page){
  $$('.nav-item').forEach(b=>b.classList.toggle('active', b.dataset.page===page));
  $$('.page').forEach(p=>p.classList.remove('active'));
  const target = $('#page-'+page) || $('#page-dashboard');
  target.classList.add('active');
  if(page==='dashboard') loadDashboard();
  if(page==='orders') loadOrders();
  if(page==='receipt') loadReceipt();
  if(page==='settings') loadSettingsInfo();
}
$$('.nav-item').forEach(b=>b.onclick=()=>navigate(b.dataset.page));

function selectRow(tableId, tr){
  $$('#'+tableId+' tbody tr').forEach(r=>r.classList.remove('selected'));
  tr.classList.add('selected');
}

// ─────────────────────────────────────────────
// 표 범위 선택 / Ctrl+C Excel 복사
// ─────────────────────────────────────────────
const rangeState = new WeakMap();
function bindCopy(tableId){
  const table = $('#'+tableId);
  if(!table) return;
  table.tabIndex = 0;
  table.addEventListener('click', e=>{
    const td = e.target.closest('td,th'); if(!td || !table.contains(td)) return;
    const cell = {row:td.parentElement.rowIndex, col:td.cellIndex};
    const state = rangeState.get(table) || {};
    clearCellSelection(table);
    if(e.shiftKey && state.anchor){
      selectCellRange(table, state.anchor, cell);
      table.focus();
    }
    else {
      td.classList.add('cell-selected');
      state.anchor = cell;
      rangeState.set(table, state);
      // contenteditable 셀은 표가 포커스를 뺏지 않게 하여 1회 클릭으로 바로 수정 가능하게 한다.
      if(td.isContentEditable){
        setTimeout(()=>deverpFocusEditableCell(td, e), 0);
      }else{
        table.focus();
      }
    }
  });
  table.addEventListener('keydown', e=>{
    if(e.ctrlKey && e.key.toLowerCase()==='a'){
      e.preventDefault(); clearCellSelection(table); $$('tbody tr', table).forEach(tr=>tr.classList.add('selected'));
    }
    if(e.ctrlKey && e.key.toLowerCase()==='c'){
      e.preventDefault(); copyTable(table);
    }
  });
}
function clearCellSelection(table){ $$('td.cell-selected,th.cell-selected', table).forEach(c=>c.classList.remove('cell-selected')); $$('tbody tr.selected', table).forEach(r=>r.classList.remove('selected')); }
function selectCellRange(table, a, b){
  const r1=Math.min(a.row,b.row), r2=Math.max(a.row,b.row), c1=Math.min(a.col,b.col), c2=Math.max(a.col,b.col);
  for(let r=r1;r<=r2;r++){ const row=table.rows[r]; if(!row) continue; for(let c=c1;c<=c2;c++){ if(row.cells[c]) row.cells[c].classList.add('cell-selected'); } }
}

function deverpFocusEditableCell(td, ev){
  if(!td || !td.isContentEditable) return;
  try{ td.focus({preventScroll:true}); }catch(e){ try{ td.focus(); }catch(_e){} }
  // 클릭한 위치에 커서를 놓되, 브라우저가 지원하지 않으면 셀 끝으로 이동한다.
  try{
    let range = null;
    if(ev && typeof document.caretPositionFromPoint === 'function'){
      const pos = document.caretPositionFromPoint(ev.clientX, ev.clientY);
      if(pos){ range = document.createRange(); range.setStart(pos.offsetNode, pos.offset); range.collapse(true); }
    }else if(ev && typeof document.caretRangeFromPoint === 'function'){
      range = document.caretRangeFromPoint(ev.clientX, ev.clientY);
    }
    const sel = window.getSelection && window.getSelection();
    if(range && sel){ sel.removeAllRanges(); sel.addRange(range); return; }
  }catch(e){}
  try{
    const range = document.createRange();
    range.selectNodeContents(td);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }catch(e){}
}

function copyTable(table){
  const selectedCells=$$('td.cell-selected,th.cell-selected',table);
  if(selectedCells.length){
    const rows=[...new Set(selectedCells.map(c=>c.parentElement.rowIndex))].sort((a,b)=>a-b);
    const cols=[...new Set(selectedCells.map(c=>c.cellIndex))].sort((a,b)=>a-b);
    const text=rows.map(r=>cols.map(c=>(table.rows[r]?.cells[c]?.innerText||'').replace(/\n/g,' ').trim()).join('\t')).join('\n');
    navigator.clipboard.writeText(text); return;
  }
  const headers = $$('thead th', table).map(th=>th.innerText.trim()).join('\t');
  const selectedRows = $$('tbody tr.selected', table);
  const rowSource = selectedRows.length ? selectedRows : $$('tbody tr', table);
  const rows = rowSource.map(tr=>$$('td', tr).map(td=>td.innerText.replace(/\n/g,' ').trim()).join('\t')).join('\n');
  navigator.clipboard.writeText(headers+'\n'+rows);
}
['orders-table','receipt-table','vendors-table','pr-items','actual-items','dashboard-orders'].forEach(bindCopy);

function deverpIsVendorTotalRow(tr){ return !!(tr && tr.classList && tr.classList.contains('vendor-total-row')); }
function deverpRenumberItemRows(tableId){
  let n = 1;
  $$('#'+tableId+' tbody tr').forEach(tr=>{
    if(deverpIsVendorTotalRow(tr)) return;
    if(tr.children[0]) tr.children[0].textContent = n++;
  });
}
function deverpRemoveVendorTotalRows(tableId){
  $$('#'+tableId+' tbody tr.vendor-total-row').forEach(tr=>tr.remove());
}
function deverpItemAmountValue(it){
  const amount = parseFloat(String(it.amount||'0').replace(/,/g,'')) || 0;
  if(amount) return Math.round(amount);
  const p = parseFloat(String(it.unit_price||'0').replace(/,/g,'')) || 0;
  const q = parseFloat(String(it.quantity||'0').replace(/,/g,'')) || 0;
  return Math.round(p*q);
}
function deverpFormatWon(v){ return (Math.round(Number(v)||0)).toLocaleString(); }
function deverpVendorLabelFromItem(it, idx){
  if(it.vendor_name) return it.vendor_name;
  if(it.vendor) return it.vendor;
  if(it.vendor_index !== undefined && it.vendor_index !== null && parsedVendors && parsedVendors[it.vendor_index]) return parsedVendors[it.vendor_index].name || parsedVendors[it.vendor_index].vendor_name || `업체${idx+1}`;
  return '업체 미지정';
}
function deverpVendorTotalsFromItems(items){
  const map = new Map();
  (items||[]).forEach((it, idx)=>{
    const key = String(it.vendor_index ?? '') + '|' + deverpVendorLabelFromItem(it, idx);
    const name = deverpVendorLabelFromItem(it, idx);
    const cur = map.get(key) || {name, count:0, total:0};
    cur.count += 1;
    cur.total += deverpItemAmountValue(it);
    map.set(key, cur);
  });
  return Array.from(map.values()).filter(v=>v.count || v.total);
}
function deverpRenderVendorSubtotalRows(tableId='pr-items'){
  const tbody = $('#'+tableId+' tbody'); if(!tbody) return;
  deverpRemoveVendorTotalRows(tableId);
  if(tableId !== 'pr-items') return;
  const rows = $$('#'+tableId+' tbody tr').filter(tr=>!deverpIsVendorTotalRow(tr));
  if(!rows.length) return;
  const groups = [];
  let current = null;
  rows.forEach(tr=>{
    const name = tr.dataset.vendorName || '업체 미지정';
    const key = String(tr.dataset.vendorIndex ?? '') + '|' + name;
    if(!current || current.key !== key){
      current = {key, name, rows:[], total:0};
      groups.push(current);
    }
    current.rows.push(tr);
    current.total += parseFloat((tr.children[6]?.innerText||'0').replace(/,/g,'')) || 0;
  });
  if(groups.length <= 1 && !groups[0]?.name) return;
  groups.forEach(g=>{
    const last = g.rows[g.rows.length - 1];
    if(!last) return;
    const tr = document.createElement('tr');
    tr.className = 'vendor-total-row';
    tr.dataset.vendorTotal = '1';
    const vals = ['', `합계금액(${g.name || '업체 미지정'})`, '', '', '', '', deverpFormatWon(g.total), '', `${g.rows.length}개 품목`];
    vals.forEach((v,i)=>{
      const td = document.createElement('td');
      td.textContent = v;
      if(i === 1) td.colSpan = 5;
      if(i > 1 && i < 6) return;
      tr.appendChild(td);
    });
    last.insertAdjacentElement('afterend', tr);
  });
  deverpRenumberItemRows(tableId);
}
function addItemRow(tableId, item={}){
  const tbody = $('#'+tableId+' tbody'); if(!tbody) return;
  if(tableId === 'pr-items') deverpRemoveVendorTotalRows(tableId);
  const tr = document.createElement('tr');
  tr.dataset.vendorName = item.vendor_name || item.vendor || '';
  tr.dataset.vendorIndex = item.vendor_index ?? '';
  const idx = $$('#'+tableId+' tbody tr').filter(x=>!deverpIsVendorTotalRow(x)).length + 1;
  const amount = item.amount || ((Number(item.unit_price||0) * Number(item.quantity||0)) || '');
  const vals = [idx, item.item_name||'', item.spec||'', item.unit_price||'', item.quantity||'', item.unit||'EA', amount, item.axis||'', item.maker||item.note||''];
  vals.forEach((v,i)=>{
    const td=document.createElement('td'); td.textContent = v;
    if(i>0){td.contentEditable='true'; if(i===3 || i===4) td.addEventListener('input',()=>{calcItemAmount(tr); if(tableId==='pr-items') deverpRenderVendorSubtotalRows(tableId);});}
    tr.appendChild(td);
  });
  tr.onclick=()=>selectRow(tableId,tr);
  tbody.appendChild(tr);
  calcItemAmount(tr);
}
function isBlankItemRow(tr){ return !tr || deverpIsVendorTotalRow(tr) || ![1,2,3,4,8].some(i=>String(tr.children[i]?.innerText||'').trim()); }
function clearDefaultBlankRows(tableId){ const tbody=$('#'+tableId+' tbody'); if(tbody && tbody.children.length===1 && isBlankItemRow(tbody.children[0])) tbody.innerHTML=''; }
function delSelectedRow(tableId){
  const tbody=$('#'+tableId+' tbody'); if(!tbody) return;
  if(tableId === 'pr-items') deverpRemoveVendorTotalRows(tableId);
  const sel=$$('#'+tableId+' tbody tr.selected').filter(tr=>!deverpIsVendorTotalRow(tr));
  const fallback = Array.from(tbody.children).reverse().find(tr=>!deverpIsVendorTotalRow(tr));
  (sel.length?sel:[fallback]).forEach(tr=>tr&&tr.remove());
  deverpRenumberItemRows(tableId);
  if(!$$('#'+tableId+' tbody tr').filter(tr=>!deverpIsVendorTotalRow(tr)).length) addItemRow(tableId);
  if(tableId === 'pr-items') deverpRenderVendorSubtotalRows(tableId);
}
function calcItemAmount(tr){
  if(deverpIsVendorTotalRow(tr)) return;
  const p = parseFloat((tr.children[3].innerText||'0').replace(/,/g,'')) || 0;
  const q = parseFloat((tr.children[4].innerText||'0').replace(/,/g,'')) || 0;
  tr.children[6].innerText = p*q ? Math.round(p*q).toLocaleString() : '';
}
function getItems(tableId){
  return $$('#'+tableId+' tbody tr').filter(tr=>!deverpIsVendorTotalRow(tr)).map(tr=>({
    item_name: tr.children[1].innerText.trim(),
    spec: tr.children[2].innerText.trim(),
    unit_price: parseFloat((tr.children[3].innerText||'0').replace(/,/g,''))||0,
    quantity: parseFloat((tr.children[4].innerText||'0').replace(/,/g,''))||0,
    unit: tr.children[5].innerText.trim()||'EA',
    amount: parseFloat((tr.children[6].innerText||'0').replace(/,/g,''))||0,
    axis: tr.children[7].innerText.trim(),
    maker: tr.children[8].innerText.trim(),
    // 수기 입력 행은 dataset.vendorName이 없으므로 비고(제조사)/maker를 업체 구분 후보로 함께 보낸다.
    vendor_name: tr.dataset.vendorName || tr.children[8].innerText.trim() || '',
    note: tr.children[8].innerText.trim(),
    vendor_index: tr.dataset.vendorIndex === '' ? null : Number(tr.dataset.vendorIndex)
  })).filter(x=>x.item_name || x.spec);
}
function updateTitlePreview(){
  const parts = [$('#pr-project-code').value,$('#pr-category').value,$('#pr-sub-category').value,$('#pr-item-type').value].filter(Boolean).map(x=>`[${x}]`).join(' ');
  const main=$('#pr-title-main').value || 'OOO을 위한 OOO';
  $('#pr-title-preview').textContent = `${parts} ${main} 구매의 건`;
}
['pr-project-code','pr-category','pr-sub-category','pr-item-type','pr-title-main'].forEach(id=>$('#'+id)?.addEventListener('input',updateTitlePreview));
$('#actual-diff')?.addEventListener('change',()=>$('#actual-box').classList.toggle('hidden', !$('#actual-diff').checked));
if($('#pr-items tbody') && !$('#pr-items tbody').children.length) addItemRow('pr-items');
if($('#actual-items tbody') && !$('#actual-items tbody').children.length) addItemRow('actual-items');

// ─────────────────────────────────────────────
// 견적서 여러 개 인식: 1개 견적서 = 1개 업체
// ─────────────────────────────────────────────
$('#estimate-btn')?.addEventListener('click', ()=> $('#estimate-file').click());
$('#estimate-file')?.addEventListener('change', async e=>{
  const files = Array.from(e.target.files || []);
  if(!files.length) return;
  const status=$('#estimate-status');
  status.textContent = `견적서 ${files.length}개 인식 중... 기존 파서로 빠르게 분석합니다.`;
  const fd = new FormData(); files.forEach(f=>fd.append('files', f));
  try{
    const controller = new AbortController();
    const timeoutId = setTimeout(()=>controller.abort(), 120000);
    const res = await fetch('/api/purchase/estimate/parse_multiple', {method:'POST', headers: TOKEN?{Authorization:`Bearer ${TOKEN}`}:{}, body:fd, signal: controller.signal});
    clearTimeout(timeoutId);
    const rawText = await res.text();
    let data = {};
    try { data = rawText ? JSON.parse(rawText) : {}; }
    catch(parseErr) {
      const msg = rawText && rawText.trim() ? rawText.trim().slice(0, 300) : '서버가 JSON이 아닌 응답을 반환했습니다.';
      throw new Error(`견적서 인식 서버 오류: ${msg}`);
    }
    if(!res.ok || !data.success) throw new Error(data.message || data.detail || '견적서 인식 실패');
    clearDefaultBlankRows('pr-items');
    let added=0;
    (data.files||[]).forEach((file, fileIndex)=>{
      const vendorName = file.vendor_name || `업체${parsedVendors.length+1}`;
      const vendorInfo = file.vendor_info || {};
      const v = {
        name: vendorName, vendor_name: vendorName,
        email: vendorInfo.email || '', contact: vendorInfo.contact || vendorInfo.phone || '',
        phone: vendorInfo.phone || '', ceo: vendorInfo.ceo || '', biz_no: vendorInfo.biz_no || '', address: vendorInfo.address || '',
        file_name: file.filename || '', saved_path: file.saved_path || '', vendor_index: parsedVendors.length, reason: '기존거래업체', reason: '기존거래업체'
      };
      parsedVendors.push(v);
      if(file.saved_path) parsedEstimateFiles.push(file.saved_path);
      (file.items||[]).forEach(it=>{ addItemRow('pr-items', {...it, vendor_name:vendorName, vendor_index:v.vendor_index}); added++; });
    });
    if(!$('#pr-items tbody').children.length) addItemRow('pr-items');
    deverpRenderVendorSubtotalRows('pr-items');
    const vendorText = parsedVendors.map(v=>v.name).join(', ');
    const totals = deverpVendorTotalsFromItems(getItems('pr-items'));
    const totalText = totals.length ? `<br><span class="vendor-badge">업체별 합계: ${esc(totals.map(v=>`${v.name} ${deverpFormatWon(v.total)}원`).join(' / '))}</span>` : '';
    status.innerHTML = `✅ ${added}개 품목 인식 완료 <span class="vendor-badge">업체: ${esc(vendorText||'미확인')}</span>${totalText}` + (data.errors?.length?`<br>⚠ ${esc(data.errors.join(' / '))}`:'');
  }catch(err){
    const msg = err.name === 'AbortError' ? '견적서 인식 시간이 2분을 초과했습니다. 파일 형식이나 크기를 확인하세요.' : err.message;
    status.textContent = '❌ 인식 실패: '+msg;
    alert(msg);
  }
  finally{ e.target.value=''; }
});

function deverpApprovalCleanText(v){
  return String(v ?? '').replace(/\s+/g, ' ').trim();
}

function deverpApprovalNormalize(v){
  return deverpApprovalCleanText(v).toLowerCase().replace(/[\[\]\(\)\{\}\s_-]+/g, '');
}

function deverpApprovalProjectDiffMessage(payload){
  const selectedProject = deverpApprovalCleanText($('#pr-project-base')?.value || payload.project_code || '');
  const actualProject = deverpApprovalCleanText(payload.project_name || '');
  if(!selectedProject || !actualProject) return '';
  const a = deverpApprovalNormalize(selectedProject);
  const b = deverpApprovalNormalize(actualProject);
  if(!a || !b || a === b || b.includes(a) || a.includes(b)) return '';
  return `1. 실제 사용되는 프로젝트는 '${actualProject}'입니다.`;
}

function deverpApprovalActualItemsTable(items){
  const rows = (items || []).filter(it=>deverpApprovalCleanText(it.item_name || it.spec));
  if(!rows.length) return '';
  const header = ['No', '품명', '규격', '수량', '단위', '축 구분', '비고(제조사)'];
  const body = rows.map((it, idx)=>[
    String(idx + 1),
    deverpApprovalCleanText(it.item_name),
    deverpApprovalCleanText(it.spec),
    deverpApprovalCleanText(it.quantity),
    deverpApprovalCleanText(it.unit || 'EA'),
    deverpApprovalCleanText(it.axis),
    deverpApprovalCleanText(it.maker || it.note)
  ]);
  return [header.join('\t')].concat(body.map(r=>r.join('\t'))).join('\n');
}

function deverpApprovalVendorTotalsTable(items){
  const rows = deverpVendorTotalsFromItems(items || []);
  if(!rows.length) return '';
  const header = ['No', '업체명', '품목수', '합계금액'];
  const body = rows.map((v, idx)=>[
    String(idx + 1),
    deverpApprovalCleanText(v.name || '업체 미지정'),
    String(v.count || 0),
    deverpFormatWon(v.total || 0) + '원'
  ]);
  return [header.join('\t')].concat(body.map(r=>r.join('\t'))).join('\n');
}

function deverpBuildApprovalCopyMessage(payload){
  const sections = [];
  const projectMsg = deverpApprovalProjectDiffMessage(payload);
  if(projectMsg) sections.push(projectMsg);

  const vendorTotals = deverpApprovalVendorTotalsTable(payload.items || []);
  if(vendorTotals){
    const no = sections.length + 1;
    sections.push(`${no}. 업체별 견적 합계입니다.\n${vendorTotals}`);
  }

  if(payload.actual_received_diff){
    const table = deverpApprovalActualItemsTable(payload.actual_items || []);
    if(table){
      const no = sections.length + 1;
      sections.push(`${no}. 실제 입고품 리스트니 참고부탁드립니다.\n${table}`);
    }
  }

  const no = sections.length + 1;
  sections.push(`${no}. DEV_ERP로 작성된 구매의뢰서입니다\n   (접속주소: 192.168.100.180:8000)`);
  return sections.join('\n\n');
}

function deverpShowApprovalCopyMessage(message){
  const text = String(message || '').trim();
  if(!text) return;
  const body = `<p class="small-info">아래 내용을 복사해서 Bizbox 결재 메시지/의견란에 붙여넣으세요.</p>
    <textarea id="approval-copy-message" readonly style="width:100%;min-height:220px;box-sizing:border-box;font-family:Consolas,'Malgun Gothic',monospace;font-size:13px;line-height:1.55;padding:10px;border:1px solid #d1d5db;border-radius:8px;white-space:pre;">${esc(text)}</textarea>`;
  const copyFn = async()=>{
    const el = document.getElementById('approval-copy-message');
    const v = el ? el.value : text;
    try{
      await navigator.clipboard.writeText(v);
      alert('결재 메시지를 클립보드에 복사했습니다.');
    }catch(e){
      if(el){ el.focus(); el.select(); }
      alert('자동 복사에 실패했습니다. 표시된 내용을 Ctrl+C로 복사하세요.');
    }
  };
  if(typeof openModal === 'function'){
    openModal('결재상신 메시지 복사', body, [['📋 메시지 복사', copyFn]]);
    setTimeout(()=>{
      const el = document.getElementById('approval-copy-message');
      if(el){ el.focus(); el.select(); }
    }, 100);
  }else{
    alert(text);
  }
}

$('#pr-submit').onclick = async()=>createPurchase(false);
$('#pr-complete').onclick = async()=>createPurchase(true);
async function createPurchase(markComplete){
  const items=getItems('pr-items');
  if(!items.length){alert('품목을 입력하세요.');return;}
  const actualItems = getItems('actual-items');
  const actualDiff = !!$('#actual-diff')?.checked;
  // 비용처리/발주관리 기준 업체는 항상 최종 구매의뢰 품목표(items) 기준입니다.
  // 실제 입고품 다름 체크 시에도 vendors_json은 비용처리용 견적/최종 품목 업체를 보존하고,
  // 입고관리/QR 업체는 actual_items의 vendor_name/업체명 칼럼에서 별도 추론합니다.
  const first=items[0];
  const settings=JSON.parse(localStorage.getItem('deverp_settings')||'{}');
  const bizMode = (settings.bizbox_mode || 'client').toLowerCase();
  const vendors = (typeof getPurchaseVendorsForSubmit === 'function') ? getPurchaseVendorsForSubmit(items) : (parsedVendors.length ? parsedVendors : uniqueVendorsFromItems(items));
  const purchasePurpose = (typeof getPurchasePurpose === 'function') ? getPurchasePurpose() : $('#pr-title-preview').textContent;
  const payload={
    project_code:$('#pr-project-code').value.trim(), project_year:$('#pr-project-year')?.value?.trim() || '', category:$('#pr-category').value.trim(), sub_category:$('#pr-sub-category').value.trim(), item_type:$('#pr-item-type').value.trim(), budget_type:$('#pr-item-type').value.trim(), title_main:$('#pr-title-main').value.trim(), title_full:(typeof getFinalTitle === 'function' ? getFinalTitle() : ($('#pr-title-preview')?.textContent||'')), project_name:$('#pr-project-name').value.trim(),
    item_name:first.item_name, spec:first.spec, quantity:first.quantity||1, unit:first.unit||'EA', unit_price:first.unit_price||0,
    reason:purchasePurpose, purpose:purchasePurpose, purpose_detail:purchasePurpose, requester:$('#pr-requester').value||USER?.name||'', department:$('#pr-department').value||USER?.department||'', required_date:$('#pr-required-date').value||new Date().toISOString().slice(0,10),
    items, actual_received_diff:actualDiff, actual_items:actualItems, vendors, attach_files: parsedEstimateFiles,
    approval_message: '',
    // client 모드에서는 서버가 아니라 웹 접속 PC의 로컬 에이전트가 Selenium을 실행한다.
    automation_target: bizMode,
    bizbox_id: bizMode === 'server' ? (settings.biz_id || '') : '',
    bizbox_pw: bizMode === 'server' ? (settings.biz_pw || '') : ''
  };
  payload.approval_message = deverpBuildApprovalCopyMessage(payload);
  try{
    let reqId = currentRequestId;
    let createRes = null;
    if(!reqId){
      createRes=await apiFetch('/api/purchase/request',{method:'POST',body:JSON.stringify(payload)});
      reqId = createRes.id || createRes.request_id; currentRequestId = reqId;
    }
    if(markComplete){
      const custom=$('#custom-request-no').value.trim();
      if(!custom){ alert('상신완료 처리 전 구매의뢰서 번호를 입력하세요.'); return; }
      const r=await apiFetch(`/api/purchase/request/${reqId}/mark_submitted`,{method:'POST',body:JSON.stringify({
        custom_request_no:custom,
        // 결재상신 후 화면에서 수기 추가/수정한 품목·업체도 상신완료 시 서버에 재반영한다.
        items,
        vendors,
        actual_received_diff:actualDiff,
        actual_items:actualItems,
        attach_files: parsedEstimateFiles
      })});
      {
        const orderCnt = (r.total_orders ?? r.created_orders ?? 0);
        const itemCnt = (r.total_items ?? r.created_items ?? 0);
        const qrCnt = (r.total_qr ?? r.created_qr ?? 0);
        const extra = r.errors && r.errors.length ? '\n\n⚠ 일부 오류:\n' + r.errors.join('\n') : '';
        alert((r.message || `상신완료 처리되었습니다.\n발주서 ${orderCnt}건 / 품목 ${itemCnt}개 / QR ${qrCnt}개 준비 완료`) + extra);
      }
      resetPurchaseForm(); loadOrders(); navigate('orders');
    } else {
      deverpShowApprovalCopyMessage(payload.approval_message);
      if((settings.biz_id || '') && (settings.biz_pw || '') && bizMode === 'client'){
        if(!createRes || !createRes.bizbox_job){
          throw new Error('구매의뢰는 등록되었지만 클라이언트 자동화 작업 정보를 받지 못했습니다. 서버 패치가 정상 적용되었는지 확인하세요.');
        }
        await deverpRunClientPurchaseAutomation(createRes.bizbox_job, settings);
        alert('구매의뢰 등록 및 클라이언트 PC Bizbox 결재 상신을 시작했습니다.');
      }else{
        alert((settings.biz_id && settings.biz_pw) ? '구매의뢰 등록 및 결재 상신을 시작했습니다.' : '구매의뢰가 등록되었습니다. Bizbox 계정이 없으면 자동상신은 실행되지 않습니다.');
      }
    }
  }catch(e){alert(e.message);}
}
function uniqueVendorsFromItems(items){
  const m=new Map();
  items.forEach((it,i)=>{
    const n=(it.vendor_name || it.vendor || it.maker || it.note || '미정').trim() || '미정';
    if(!m.has(n)) m.set(n,{name:n,vendor_name:n,email:'',contact:'',vendor_index:i,reason:'기존거래업체'});
  });
  return Array.from(m.values());
}
function resetPurchaseForm(){
  currentRequestId=null; parsedVendors=[]; parsedEstimateFiles=[]; $('#pr-items tbody').innerHTML=''; $('#actual-items tbody').innerHTML=''; addItemRow('pr-items'); addItemRow('actual-items'); $('#estimate-status').textContent='견적서는 여러 개 선택할 수 있으며, 1개 견적서 = 1개 업체 기준으로 품목이 누적됩니다.'; $('#custom-request-no').value='';
}

async function loadDashboard(){
  try{
    const ord = await apiFetch('/api/purchase/orders/detail');
    dashboardOrders = ord || [];
    renderDashboard();
  }catch(e){ console.warn(e); }
}
function orderDueState(o){
  if(!o.delivery_date) return {state:'미지정', days:'', cls:''};
  const today=new Date(); today.setHours(0,0,0,0);
  const d=new Date(o.delivery_date); d.setHours(0,0,0,0);
  const diff=Math.ceil((d-today)/86400000);
  if(diff<0) return {state:'지연', days:diff, cls:'delayed'};
  if(diff<=7) return {state:'임박', days:diff, cls:'soon'};
  return {state:'정상', days:diff, cls:'normal'};
}
function renderDashboard(){
  // 모든 품목이 입고 처리된 구매의뢰서는 대시보드에서 제외한다.
  // 일부 품목이라도 미입고이면 납기일 기준으로 정상/임박/지연에 계속 표시한다.
  const active=dashboardOrders.filter(o=>!o.all_items_received && !['입고완료','완료','삭제'].includes(o.status||''));
  const delayed=active.filter(o=>orderDueState(o).cls==='delayed');
  const soon=active.filter(o=>orderDueState(o).cls==='soon');
  $('#dash-order').textContent=active.length; $('#dash-delay').textContent=delayed.length; $('#dash-soon').textContent=soon.length;
  const rows = dashboardFilter==='delayed'?delayed:dashboardFilter==='soon'?soon:active;
  const tbody=$('#dashboard-orders tbody'); if(!tbody) return; tbody.innerHTML='';
  rows.forEach(o=>{
    const st=orderDueState(o);
    const tr=document.createElement('tr');
    const itemCountText = o.receipt_total_count ? `${esc(o.receipt_received_count||0)}/${esc(o.receipt_total_count)}` : `${(o.items||[]).length}`;
    tr.innerHTML=`<td>${esc(st.state)}</td><td>${esc(o.request_no||o.order_no||'')}</td><td>${esc(o.title_full||'')}</td><td>${esc(o.vendor_name||'')}</td><td>${esc(o.status||'')}</td><td>${esc(o.delivery_date||'')}</td><td>${esc(st.days)}</td><td>${itemCountText}</td><td>${esc(o.requested_by||o.requester||'')}</td><td>${esc(o.order_completed_by||'')}</td>`;
    tr.onclick=()=>openOrderDetail(o,st);
    tbody.appendChild(tr);
  });
}
$$('[data-dash-filter]').forEach(c=>c.onclick=()=>{ dashboardFilter=c.dataset.dashFilter; renderDashboard(); });
function openOrderDetail(o,st){
  const isAdmin = USER?.role === 'admin';
  const ro = isAdmin ? '' : ' readonly';
  const tdEdit = isAdmin ? ' contenteditable="true"' : '';
  const items=(o.items||[]).map((it,i)=>`<tr data-item-id="${esc(it.id||'')}"><td>${i+1}</td><td${tdEdit} data-field="item_name">${esc(it.item_name||'')}</td><td${tdEdit} data-field="spec">${esc(it.spec||'')}</td><td${tdEdit} data-field="quantity">${esc(`${it.quantity||''} ${it.unit||'EA'}`.trim())}</td></tr>`).join('');
  const body = `<div class="kv dash-detail-kv">
    <label>납기상태</label><input value="${esc(st.state)}" readonly>
    <label>남은일수</label><input value="${esc(st.days)}" readonly>
    <label>구매의뢰번호</label><input id="dash-detail-request-no" value="${esc(o.request_no||'')}"${ro}>
    <label>업체</label><input id="dash-detail-vendor" value="${esc(o.vendor_name||'')}"${(isAdmin && Number(o.vendor_count||1)<=1)?'':' readonly'}>
    <label>제목</label><input id="dash-detail-title" value="${esc(o.title_full||'')}"${ro}>
    <label>실제 프로젝트</label><input id="dash-detail-project-name" value="${esc(o.project_name||o.actual_project||'')}"${ro}>
    <label>입고요청일</label><input id="dash-detail-delivery" value="${esc(o.delivery_date||'')}"${ro}>
    <label>구매의뢰자</label><input id="dash-detail-requested-by" value="${esc(o.requested_by||o.requester||'')}"${ro}>
    <label>발주자</label><input id="dash-detail-order-by" value="${esc(o.order_completed_by||'')}"${ro}>
    <label>입고자</label><input id="dash-detail-inbound-by" value="${esc(o.inbound_by||'')}"${ro}>
    <label>출고자</label><input id="dash-detail-outbound-by" value="${esc(o.outbound_by||'')}"${ro}>
  </div>
  ${isAdmin && Number(o.vendor_count||1)>1 ? '<p class="muted">여러 업체가 묶인 건은 업체명을 여기서 일괄 수정하지 않습니다. 업체별 수정은 발주 관리/입고 관리에서 진행하세요.</p>' : ''}
  <br><table id="dash-detail-items" class="grid${isAdmin?' editable':''}"><thead><tr><th>No</th><th>품명</th><th>규격</th><th>수량</th></tr></thead><tbody>${items}</tbody></table>`;
  const actions = [];
  if(isAdmin){
    actions.push(['저장', async()=>{
      const payload = {
        request_no: ($('#dash-detail-request-no')?.value || '').trim(),
        vendor_name: ($('#dash-detail-vendor')?.value || '').trim(),
        title_full: ($('#dash-detail-title')?.value || '').trim(),
        project_name: ($('#dash-detail-project-name')?.value || '').trim(),
        delivery_date: ($('#dash-detail-delivery')?.value || '').trim(),
        requested_by: ($('#dash-detail-requested-by')?.value || '').trim(),
        order_completed_by: ($('#dash-detail-order-by')?.value || '').trim(),
        inbound_by: ($('#dash-detail-inbound-by')?.value || '').trim(),
        outbound_by: ($('#dash-detail-outbound-by')?.value || '').trim(),
        items: $$('#dash-detail-items tbody tr').map(tr=>({
          id: Number(tr.dataset.itemId || 0),
          item_name: (tr.querySelector('[data-field="item_name"]')?.innerText || '').trim(),
          spec: (tr.querySelector('[data-field="spec"]')?.innerText || '').trim(),
          quantity: (tr.querySelector('[data-field="quantity"]')?.innerText || '').trim()
        })).filter(x=>x.id)
      };
      try{
        const res = await apiFetch(`/api/purchase/order/${encodeURIComponent(o.id||o.order_id||0)}/dashboard_detail_update`, {method:'POST', body:JSON.stringify(payload)});
        alert(res.message || '저장되었습니다.');
        closeModal();
        await loadDashboard();
        try{ await loadReceipt(); }catch(_e){}
      }catch(e){ alert(e.message); }
    }]);
  }
  openModal('발주/납기 상세', body, actions);
  if(isAdmin) bindCopy('dash-detail-items');
}


async function loadOrders(){
  const data=await apiFetch('/api/purchase/orders/detail');
  const tbody=$('#orders-table tbody'); tbody.innerHTML='';
  data.forEach(o=>{
    const tr=document.createElement('tr');
    const orderId = Number(o.id || o.order_id || 0);
    tr.dataset.orderId = orderId;
    tr.innerHTML=`<td>${esc(o.request_no||o.order_no||'')}</td><td>${esc(o.project_name||o.actual_project||'')}</td><td>${esc(o.title_full||o.title||'')}</td><td>${esc(o.vendor_name||'')}</td><td>${esc(o.status||'')}</td><td>${esc(o.delivery_date||'')}</td><td>${o.qr_count||o.items?.length||''}</td><td>${esc(o.representative_qr||o.qr_code||'')}</td><td>${orderId ? `<a class="linkbtn qr-open-link" target="_blank" href="/api/purchase/order/${orderId}/qr_page" onclick="event.stopPropagation();">열기</a>` : ''}</td>`;
    tr.onclick=()=>{selectedOrderId=orderId; selectedOrder=o; selectRow('orders-table',tr);};
    tbody.appendChild(tr);
  });
}

function openQrList(orderId){
  orderId = Number(orderId || selectedOrderId || 0);
  if(!orderId){ alert('QR을 열 발주 건을 선택하세요.'); return; }
  window.open(`/api/purchase/order/${orderId}/qr_page`, '_blank');
}
window.openQrListSafe = openQrList;

document.addEventListener('click', function(ev){
  const orderBtn = ev.target.closest && ev.target.closest('.qr-open-btn');
  if(orderBtn){
    ev.preventDefault(); ev.stopPropagation();
    const id = Number(orderBtn.dataset.orderId || orderBtn.closest('tr')?.dataset.orderId || selectedOrderId || 0);
    openQrList(id);
    return false;
  }
  const itemBtn = ev.target.closest && ev.target.closest('.qr-item-open-btn,[data-qr-url]');
  if(itemBtn){
    ev.preventDefault(); ev.stopPropagation();
    const url = itemBtn.dataset.qrUrl || itemBtn.dataset.url || '';
    if(!url){ alert('QR 이미지 주소가 없습니다.'); return false; }
    window.open(normUrl(url), '_blank');
    return false;
  }
}, true);


$('#send-order').onclick=async()=>{
  if(!selectedOrderId){alert('발주 건을 선택하세요.');return;}
  const btn=$('#send-order'); const oldTxt=btn?btn.textContent:'';
  try{
    if(btn){btn.disabled=true; btn.textContent='메일 자동작성/압축 생성 중...';}
    const st = JSON.parse(localStorage.getItem('deverp_settings') || '{}');
    const bizMode = (st.bizbox_mode || 'client').toLowerCase();
    const body = {automation_target:bizMode, orderer_name:USER?.name||'', orderer_phone:st.phone||''};
    if(bizMode === 'server'){
      body.bizbox_id = st.biz_id || '';
      body.bizbox_pw = st.biz_pw || '';
    }
    const res=await apiFetch(`/api/purchase/order/${selectedOrderId}/send_bizbox_mail_group`,{
      method:'POST',
      body:JSON.stringify(body)
    });
    const urls=[];
    (res.results||[]).forEach(r=>{ if(r.package_download_url) urls.push(normUrl(r.package_download_url)); });
    for(const u of urls) await tryDownload(u);
    if(bizMode === 'client'){
      await deverpRunClientOrderMailAutomation(res.mail_jobs || [], st, res.server_base || location.origin);
      alert(`발주서 메일 자동작성 및 발주건 ZIP 생성 완료: ${res.count||0}개 업체\n웹 접속 PC의 Chrome에서 Bizbox 메일창을 열었습니다.\nZIP 파일명은 구매의뢰번호_구매의뢰제목_발주업체.zip 형식입니다.`);
    }else{
      alert(`발주서 메일 자동작성 및 발주건 ZIP 생성 완료: ${res.count||0}개 업체\n메일 본문에는 품목표/요청납기가 HTML로 자동 입력됩니다.\nZIP 파일명은 구매의뢰번호_구매의뢰제목_발주업체.zip 형식입니다.`);
    }
    loadOrders();
  }catch(e){alert(e.message);} finally{ if(btn){btn.disabled=false; btn.textContent=oldTxt;} }
};
$('#order-complete').onclick=async()=>{ if(!selectedOrderId){alert('발주 건을 선택하세요.');return;} const res=await apiFetch(`/api/purchase/order/${selectedOrderId}/mark_completed`,{method:'POST'}); alert(res.message || '발주진행완료 처리되었습니다.'); loadOrders(); };
$('#tax-docs-complete').onclick=async()=>{
  if(!selectedOrderId){alert('발주 건을 선택하세요.');return;}
  if(!confirm('선택한 구매의뢰서/업체 묶음을 세금계산서/거래명세서 처리완료 상태로 변경할까요?')) return;
  const res=await apiFetch(`/api/purchase/order/${selectedOrderId}/mark_tax_docs_completed`,{method:'POST'});
  alert(res.message || '세금계산서/거래명세서 처리완료 처리되었습니다.');
  selectedOrderId=null; selectedOrder=null;
  loadOrders(); loadDashboard();
};
$('#delete-order').onclick=async()=>{ if(USER?.role !== 'admin'){alert('관리자만 삭제할 수 있습니다.');return;} if(!selectedOrderId || !confirm('선택한 발주 건을 삭제할까요?')) return; const res=await apiFetch(`/api/purchase/order/${selectedOrderId}`,{method:'DELETE'}); alert(res.message||'삭제되었습니다.'); loadOrders(); };

async function loadReceipt(){
  try{
    const data=await apiFetch('/api/inventory/receipt_list');
    receiptRows=Array.isArray(data) ? data : [];
    renderReceipt(receiptRows);
  }catch(e){
    console.error('receipt_list load failed', e);
    receiptRows=[];
    renderReceipt(receiptRows);
    alert('입고 관리 데이터를 불러오지 못했습니다: ' + (e.message || e));
  }
}
function receiptGroupKey(group, idx=0){
  return String(group.request_no || group.order_no || group.id || idx || '');
}
function receiptGroupChildrenText(group){
  const vendorGroups = Array.isArray(group.vendor_groups) && group.vendor_groups.length
    ? group.vendor_groups
    : [{vendor_name:group.vendor_name || group.vendor || '', order_no:group.order_no, delivery_date:group.delivery_date, items:group.items||[]}];
  return JSON.stringify(vendorGroups || []).toLowerCase();
}
function receiptGroupItemCount(group){
  const vendorGroups = Array.isArray(group.vendor_groups) && group.vendor_groups.length
    ? group.vendor_groups
    : [{items:group.items||[]}];
  return vendorGroups.reduce((sum, vg)=>sum + ((vg.items || []).length), 0);
}
function receiptAdminEditableCell(it, field, value){
  const v = value ?? '';
  if(USER?.role === 'admin' && it?.id){
    return `<td contenteditable="true" data-receipt-item-id="${esc(it.id)}" data-receipt-field="${esc(field)}">${esc(v)}</td>`;
  }
  return `<td>${esc(v)}</td>`;
}
async function saveReceiptAdminCell(td){
  const id = td?.dataset?.receiptItemId;
  const field = td?.dataset?.receiptField;
  if(!id || !field || USER?.role !== 'admin') return;
  const value = (td.innerText || '').trim();
  if((td.dataset.original ?? '') === value) return;
  td.classList.add('saving');
  try{
    const payload = {}; payload[field] = value;
    await apiFetch(`/api/inventory/receipt_item/${encodeURIComponent(id)}/update`, {method:'POST', body:JSON.stringify(payload)});
    td.dataset.original = value;
    td.classList.remove('error');
  }catch(e){
    td.classList.add('error');
    alert('입고 관리 수정 실패: ' + e.message);
  }finally{
    td.classList.remove('saving');
  }
}
function bindReceiptAdminEditableCells(root=document){
  if(USER?.role !== 'admin') return;
  $$('[data-receipt-item-id][contenteditable]', root).forEach(td=>{
    if(!('original' in td.dataset)) td.dataset.original = (td.innerText || '').trim();
  });
}
function renderReceipt(data){
  const q=($('#receipt-search').value||'').toLowerCase().trim();
  const tbody=$('#receipt-table tbody'); tbody.innerHTML='';
  const hasSearch = !!q;
  const renderItemRow=(group,it,diffNote,orderNo,deliveryDate,vendorText='')=>{
    const groupText=JSON.stringify(group).toLowerCase();
    const text=JSON.stringify(it).toLowerCase();
    if(q && !text.includes(q) && !groupText.includes(q) && !vendorText.includes(q)) return false;
    const note = [it.note||'', diffNote].filter(Boolean).join(' / ');
    const photoCount = Number(it.inspection_photo_count || it.photo_count || 0);
    const photoCell = photoCount > 0
      ? `<button class="linkbtn" data-photo-id="${esc(it.id||'')}">사진 ${photoCount}장</button>`
      : 'X';
    const tr=document.createElement('tr');
    tr.className='receipt-child-row receipt-item-row';
    const itemIdNum = Number(it.id || 0);
    const checkedAttr = itemIdNum && selectedReceiptIds.has(itemIdNum) ? ' checked' : '';
    tr.innerHTML=`<td><span class="receipt-tree-cell"><span class="tree-indent item-indent"></span><input type="checkbox" data-id="${it.id||''}"${checkedAttr}> QR: ${esc(short(it.qr_code||'',12))}</span></td><td></td><td></td><td></td>`
      + receiptAdminEditableCell(it, 'purchase_recv_at', it.purchase_recv_at||it.inbound_at||it.inbound||'X')
      + receiptAdminEditableCell(it, 'quality_recv_at', it.quality_recv_at||it.outbound_at||it.outbound||'X')
      + `<td>${esc(orderNo||group.order_no||'')}</td>`
      + receiptAdminEditableCell(it, 'material_code', it.material_code||'')
      + receiptAdminEditableCell(it, 'item_name', it.item_name||'')
      + receiptAdminEditableCell(it, 'maker', it.maker||'')
      + receiptAdminEditableCell(it, 'spec', it.spec||'')
      + receiptAdminEditableCell(it, 'item_group', it.item_group||'')
      + receiptAdminEditableCell(it, 'quantity', `${it.quantity||''} ${it.unit||''}`.trim())
      + receiptAdminEditableCell(it, 'axis_type', it.axis||it.axis_type||'')
      + receiptAdminEditableCell(it, 'reason', it.reason||'')
      + receiptAdminEditableCell(it, 'order_round', it.order_round||'')
      + receiptAdminEditableCell(it, 'delivery_date', deliveryDate||group.delivery_date||'')
      + receiptAdminEditableCell(it, 'purchase_recv_at', it.purchase_recv_at||it.received_at||'X')
      + `<td>${photoCell}</td>`
      + receiptAdminEditableCell(it, 'note', note)
      + `<td></td>`
      + receiptAdminEditableCell(it, 'requested_by', group.requested_by||group.requester||'')
      + receiptAdminEditableCell(it, 'order_completed_by', group.order_completed_by||'')
      + receiptAdminEditableCell(it, 'purchase_recv_by', it.purchase_recv_by||'')
      + receiptAdminEditableCell(it, 'quality_recv_by', it.quality_recv_by||'');
    const cb=$('input',tr); cb.onchange=()=>{ if(cb.checked) selectedReceiptIds.add(Number(cb.dataset.id)); else selectedReceiptIds.delete(Number(cb.dataset.id)); };
    const pbtn=$('[data-photo-id]',tr); if(pbtn) pbtn.onclick=(ev)=>{ev.stopPropagation(); openItemPhotos(Number(pbtn.dataset.photoId));};
    tbody.appendChild(tr);
    bindReceiptAdminEditableCells(tr);
    return true;
  };
  data.forEach((group, idx)=>{
    const groupText=JSON.stringify(group).toLowerCase();
    const childrenText=receiptGroupChildrenText(group);
    if(q && !groupText.includes(q) && !childrenText.includes(q)) return;
    const key = receiptGroupKey(group, idx);
    const diffNote = group.actual_received_diff ? '실제 입고품 다름' : '';
    const expanded = hasSearch || receiptExpandedGroups.has(key);
    const itemCount = receiptGroupItemCount(group);
    const gtr=document.createElement('tr'); gtr.className='group-row receipt-root-row';
    gtr.dataset.receiptGroupKey = key;
    const vendorLabel = group.vendor_name || group.vendor || '';
    const vendorGroupsForSelect = Array.isArray(group.vendor_groups) && group.vendor_groups.length ? group.vendor_groups : [{vendor_name:vendorLabel, order_no:group.order_no, delivery_date:group.delivery_date, items:group.items||[]}];
    const groupItemIds = vendorGroupsForSelect.flatMap(vg=>(vg.items||[]).map(it=>Number(it.id||0)).filter(Boolean));
    const groupChecked = groupItemIds.length && groupItemIds.every(id=>selectedReceiptIds.has(id));
    const groupIndeterminate = groupItemIds.some(id=>selectedReceiptIds.has(id)) && !groupChecked;
    const toggleMark = expanded ? '−' : '+';
    const toggleTitle = expanded ? '품목 접기' : '품목 펼치기';
    gtr.innerHTML=`<td><span class="receipt-tree-cell receipt-tree-root"><input type="checkbox" class="receipt-group-select" data-group-key="${esc(key)}" title="구매의뢰서 품목 전체 선택" ${groupChecked?'checked':''}><button type="button" class="tree-toggle ${expanded?'expanded':'collapsed'}" data-group-key="${esc(key)}" title="${toggleTitle}" aria-label="${toggleTitle}">${toggleMark}</button><b>${esc(group.request_no||group.order_no||'')}</b><span class="tree-count">품목 ${itemCount}개</span></span></td><td>${esc(group.actual_project||group.project_name_actual||'')}</td><td>${esc(group.project_code||'')}</td><td><b>${esc(group.project_name||group.title_full||'')}</b></td><td>${esc(group.actual_received_at||group.inbound_at||group.inbound||'X')}</td><td>${esc(group.actual_outbound_at||group.outbound_at||group.outbound||'X')}</td><td>${esc(group.order_no||'')}</td><td></td><td></td><td>${esc(vendorLabel)}</td><td></td><td></td><td></td><td></td><td></td><td></td><td>${esc(group.delivery_date||'')}</td><td>${esc(group.received_at||'X')}</td><td>${esc(group.photo_at||'X')}</td><td>${esc(diffNote)}</td><td>${group.list_pdf_url||group.receipt_list_url?'<button class="linkbtn" data-list-open="1">열기</button>':'없음'}</td><td>${esc(group.requested_by||group.requester||'')}</td><td>${esc(group.order_completed_by||'')}</td><td>${esc(group.inbound_by||'')}</td><td>${esc(group.outbound_by||'')}</td>`;
    const toggleReceiptGroup = ()=>{
      if(receiptExpandedGroups.has(key)) receiptExpandedGroups.delete(key); else receiptExpandedGroups.add(key);
      renderReceipt(receiptRows);
    };
    const gcb = $('.receipt-group-select', gtr);
    if(gcb){
      gcb.indeterminate = groupIndeterminate;
      gcb.onchange=(ev)=>{
        ev.stopPropagation();
        groupItemIds.forEach(id=>{ if(gcb.checked) selectedReceiptIds.add(id); else selectedReceiptIds.delete(id); });
        renderReceipt(receiptRows);
      };
      gcb.onclick=(ev)=>ev.stopPropagation();
    }
    const toggle = $('.tree-toggle', gtr);
    if(toggle) toggle.onclick=(ev)=>{
      ev.stopPropagation();
      toggleReceiptGroup();
    };
    const firstCell = $('td', gtr);
    if(firstCell) firstCell.onclick=(ev)=>{
      if(ev.target.closest('button,input,a')) return;
      toggleReceiptGroup();
    };
    gtr.ondblclick=(ev)=>{
      if(ev.target.closest('button,input,a')) return;
      toggleReceiptGroup();
    };
    const btn=$('[data-list-open]',gtr); if(btn) btn.onclick=(ev)=>{ev.stopPropagation(); downloadFile(normUrl(group.list_pdf_url||group.receipt_list_url));};
    tbody.appendChild(gtr);
    if(!expanded) return;
    const vendorGroups = Array.isArray(group.vendor_groups) && group.vendor_groups.length ? group.vendor_groups : [{vendor_name:vendorLabel, order_no:group.order_no, delivery_date:group.delivery_date, items:group.items||[]}];
    vendorGroups.forEach(vg=>{
      const vtext=JSON.stringify(vg).toLowerCase();
      if(q && !vtext.includes(q) && !groupText.includes(q)) return;
      const vtr=document.createElement('tr'); vtr.className='group-row vendor-sub-row receipt-child-row';
      vtr.innerHTML=`<td></td><td></td><td></td><td><span class="tree-indent vendor-indent"></span>↳ 업체: <b>${esc(vg.vendor_name||vg.vendor||'미정업체')}</b></td><td></td><td></td><td>${esc(vg.order_no||'')}</td><td></td><td colspan="2">품목 ${(vg.items||[]).length}개</td><td></td><td></td><td></td><td></td><td></td><td></td><td>${esc(vg.delivery_date||group.delivery_date||'')}</td><td></td><td></td><td>${esc(vg.status||'')}</td><td></td><td>${esc(vg.requested_by||group.requested_by||group.requester||'')}</td><td>${esc(vg.order_completed_by||group.order_completed_by||'')}</td><td>${esc(vg.inbound_by||'')}</td><td>${esc(vg.outbound_by||'')}</td>`;
      tbody.appendChild(vtr);
      (vg.items||[]).forEach(it=>renderItemRow(group,it,diffNote,vg.order_no||group.order_no,vg.delivery_date||group.delivery_date,vtext));
    });
  });
}
$('#receipt-search').oninput=()=>renderReceipt(receiptRows);
$('#receipt-clear').onclick=()=>{$('#receipt-search').value='';renderReceipt(receiptRows);};
document.addEventListener('blur', e=>{
  const td = e.target?.closest?.('[data-receipt-item-id][contenteditable]');
  if(td) saveReceiptAdminCell(td);
}, true);
document.addEventListener('keydown', e=>{
  const td = e.target?.closest?.('[data-receipt-item-id][contenteditable]');
  if(!td) return;
  if(e.key === 'Enter'){ e.preventDefault(); td.blur(); }
}, true);
const inBtn = $('#in-btn');
if(inBtn) inBtn.onclick=async()=>{
  if(!selectedReceiptIds.size){alert('입고 처리할 품목을 체크하세요.');return;}
  try{
    const res=await apiFetch('/api/inventory/transfer_items',{method:'POST',body:JSON.stringify({item_ids:Array.from(selectedReceiptIds),target_stage:'입고',user_name:USER?.name||USER?.username||''})});
    alert(res.message || `입고 처리되었습니다. (${res.count||0}개 품목)`);
    selectedReceiptIds.clear();
    await loadReceipt();
    await loadDashboard();
  }catch(e){alert(e.message);}
};
$('#out-btn').onclick=async()=>{ if(!selectedReceiptIds.size){alert('출고 처리할 품목을 체크하세요.');return;} try{ const res=await apiFetch('/api/inventory/transfer_items',{method:'POST',body:JSON.stringify({item_ids:Array.from(selectedReceiptIds),target_stage:'출고',user_name:USER?.name||''})}); for(const u of (res.pdf_urls||[])) await downloadFile(normUrl(u)); alert('출고 처리 및 입고목록 PDF 다운로드를 시작했습니다.'); loadReceipt(); }catch(e){alert(e.message);} };
$('#receipt-delete-btn').onclick=async()=>{
  if(!selectedReceiptIds.size){alert('삭제할 품목을 체크하세요. 선택한 입고 관리 품목만 삭제됩니다.');return;}
  const cnt = selectedReceiptIds.size;
  if(!confirm(`선택한 입고 관리 품목 ${cnt}개만 삭제할까요?\n\n구매의뢰서 전체는 삭제되지 않습니다. 단, 해당 발주 건의 품목이 모두 사라지면 빈 발주 건만 정리됩니다.`)) return;
  try{
    const res=await apiFetch('/api/inventory/receipt_items/delete',{method:'POST',body:JSON.stringify({item_ids:Array.from(selectedReceiptIds)})});
    selectedReceiptIds.clear();
    await loadReceipt();
    await loadOrders();
    await loadDashboard();
    alert(res.message||'삭제되었습니다.');
  }catch(e){alert(e.message);}
};

function ensureQualityControlButton(){
  let btn = $('#quality-control-btn');
  const receiptPage = document.querySelector('#page-receipt');
  if(!receiptPage) return btn || null;
  const legend = receiptPage.querySelector('.legend');
  const actions = receiptPage.querySelector('.title-row .actions');
  if(!btn){
    btn = document.createElement('button');
    btn.id = 'quality-control-btn';
    btn.type = 'button';
    btn.textContent = '📊 품질관리';
  }
  btn.className = 'btn purple quality-control-inline';
  btn.style.display = 'inline-flex';
  btn.style.visibility = 'visible';
  btn.hidden = false;
  if(legend && btn.parentElement !== legend){
    legend.appendChild(btn);
  }else if(!legend && actions && btn.parentElement !== actions){
    const ref = $('#in-btn') || $('#out-btn') || $('#receipt-delete-btn') || null;
    if(ref && ref.parentElement === actions) actions.insertBefore(btn, ref);
    else actions.appendChild(btn);
  }
  return btn;
}
const qualityControlBtn = ensureQualityControlButton();
if(qualityControlBtn) qualityControlBtn.onclick=async()=>{
  if(!selectedReceiptIds.size){alert('품질관리 파일로 내보낼 구매의뢰서/품목을 선택하세요. 문서번호 왼쪽 체크박스로 구매의뢰서 전체를 선택할 수 있습니다.');return;}
  const btn = qualityControlBtn;
  const oldTxt = btn.textContent;
  btn.disabled = true;
  btn.textContent = '품질관리 파일 생성 중...';
  try{
    const res = await fetch('/api/inventory/quality_control_export', {
      method:'POST',
      headers: authHeaders(true),
      body: JSON.stringify({item_ids:Array.from(selectedReceiptIds)})
    });
    if(!res.ok){
      const parsed = await deverpReadResponseJsonOrText(res);
      throw new Error(deverpResponseMessage(parsed, `HTTP ${res.status}`));
    }
    const blob = await res.blob();
    let name = '품질관리_진행LIST.xlsx';
    const cd = res.headers.get('content-disposition') || '';
    const m = cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
    if(m) name = decodeURIComponent(m[1] || m[2]);
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=name;
    a.rel='noopener';
    document.body.appendChild(a);
    a.click();
    setTimeout(()=>{ try{URL.revokeObjectURL(a.href);}catch(e){} a.remove(); },3000);
  }catch(e){alert('품질관리 파일 생성 실패: ' + e.message);} finally{btn.disabled=false; btn.textContent=oldTxt;}
};
$('#inspection-btn').onclick=()=>openInspectionModal();
async function openInspectionModal(){
  const targets=[];
  (receiptRows||[]).forEach(g=>{
    const vgs = Array.isArray(g.vendor_groups) && g.vendor_groups.length
      ? g.vendor_groups
      : [{order_no:g.raw_order_no||g.order_no, vendor_name:g.vendor_name||g.vendor||'', items:g.items||[], inspection_photo_ready:g.inspection_photo_ready, inspection_photo_missing:g.inspection_photo_missing||[], inspection_photo_total:g.inspection_photo_total||0}];
    vgs.forEach(vg=>{
      const items = vg.items || [];
      const missing = vg.inspection_photo_missing || items.filter(it=>!it.inspection_photo_ready).map(it=>it.item_name || `품목ID ${it.id}`);
      const photoTotal = Number(vg.inspection_photo_total ?? items.reduce((s,it)=>s+Number(it.inspection_photo_count||it.photo_count||0),0));
      targets.push({
        order_no: vg.order_no || g.raw_order_no || g.order_no || '',
        request_no: g.request_no || g.order_no || '',
        vendor_name: vg.vendor_name || vg.vendor || g.vendor_name || g.vendor || '',
        project_name: g.project_name || g.title_full || '',
        item_count: items.length,
        // 작성 조건: 업체별 발주 건에 검수조사서용 사진이 1장 이상이면 가능.
        ready: photoTotal > 0,
        missing,
        photoTotal
      });
    });
  });
  let html='<p>검수조사서는 구매의뢰서 전체가 아니라 <b>견적서/업체별 발주 건</b> 기준으로 XLSX 파일로 작성됩니다.<br>작성 조건: 선택한 업체/견적 건에 검수조사서용 사진이 <b>1장 이상</b> 있으면 작성됩니다. 품목별 사진 누락은 안내만 표시합니다.</p>';
  html += '<div class="table-toolbar" style="margin:10px 0;display:flex;gap:8px;align-items:center"><input id="inspection-search" placeholder="모든 칼럼 검색: 구매의뢰번호, 업체, 제목, 품목수, 사진상태, 누락품목 등" style="flex:1;min-width:360px"><button type="button" class="btn light" id="inspection-search-clear">검색 초기화</button><span id="inspection-search-count" style="color:#555;font-size:12px"></span></div>';
  html += '<table class="grid" id="inspection-target-table"><thead><tr><th>선택</th><th>구매의뢰번호</th><th>업체</th><th>제목</th><th>품목수</th><th>사진상태</th></tr></thead><tbody>';
  if(!targets.length){
    html += '<tr><td colspan="6" style="text-align:center;color:#777;padding:20px">검수조사서 작성 대상이 없습니다. 입고 관리를 새로고침한 뒤 다시 확인하세요.</td></tr>';
  }
  targets.forEach(t=>{
    const ready=t.ready?'✅ 작성가능':'❌ 사진 0장';
    const missingText=(t.missing||[]).length ? ` / 누락 ${(t.missing||[]).length}건` : '';
    const photoText = `${ready} / 사진 ${t.photoTotal||0}장${missingText}`;
    const searchText = [t.order_no, t.request_no, t.vendor_name, t.project_name, t.item_count, photoText, ...(t.missing||[])].join(' ').toLowerCase();
    html+=`<tr class="insp-target-row" data-search="${esc(searchText)}"><td><input type="radio" name="insp" value="${esc(t.order_no||'')}"></td><td>${esc(t.request_no||'')}</td><td>${esc(t.vendor_name||'')}</td><td>${esc(t.project_name||'')}</td><td>${esc(t.item_count||0)}</td><td>${esc(photoText)}</td></tr>`;
  });
  html+='</tbody></table><div id="insp-preview"><div id="inspection-photo-manager" style="margin-top:16px;color:#777;padding:10px">대상을 선택하면 업체별 입고사진 목록이 자동으로 표시됩니다.</div></div>';
  openModal('검수조사서 작성', html, [
    ['미리보기', async()=>{const orderNo=$('input[name=insp]:checked')?.value; if(!orderNo){alert('대상을 선택하세요.');return;} await loadInspectionPreview(orderNo);}],
    ['XLSX 작성/다운로드', async()=>{const orderNo=$('input[name=insp]:checked')?.value; if(!orderNo){alert('대상을 선택하세요.');return;} await createInspection(orderNo);}]
  ])
  bindInspectionTargetSearch();
  bindInspectionTargetSelection();
}


function bindInspectionTargetSearch(){
  const input = $('#inspection-search');
  const clear = $('#inspection-search-clear');
  const count = $('#inspection-search-count');
  const rows = $$('#inspection-target-table tbody tr.insp-target-row');
  if(!input || !rows.length) return;
  const apply = ()=>{
    const q = input.value.trim().toLowerCase();
    let shown = 0;
    rows.forEach(tr=>{
      const text = (tr.dataset.search || tr.innerText || '').toLowerCase();
      const ok = !q || text.includes(q);
      tr.style.display = ok ? '' : 'none';
      if(ok) shown += 1;
      if(!ok){ const r = tr.querySelector('input[type=radio]'); if(r?.checked) r.checked = false; }
    });
    if(count) count.textContent = `표시 ${shown} / 전체 ${rows.length}`;
  };
  input.addEventListener('input', apply);
  if(clear) clear.onclick = ()=>{ input.value=''; apply(); input.focus(); };
  apply();
}

function bindInspectionTargetSelection(){
  const rows = $$('#inspection-target-table tbody tr.insp-target-row');
  const loadFor = async(orderNo)=>{
    if(!orderNo) return;
    const preview = $('#insp-preview');
    if(preview && !$('#inspection-photo-manager', preview)){
      preview.innerHTML = '<div id="inspection-photo-manager" style="margin-top:16px"></div>';
    }
    await loadInspectionPhotos(orderNo);
  };
  rows.forEach(tr=>{
    const radio = $('input[name=insp]', tr);
    tr.addEventListener('click', async(e)=>{
      if(e.target && e.target.tagName && e.target.tagName.toLowerCase()==='input') return;
      if(radio){ radio.checked = true; await loadFor(radio.value); }
    });
    if(radio){
      radio.addEventListener('change', async()=>{ if(radio.checked) await loadFor(radio.value); });
    }
  });
}

async function loadInspectionPreview(orderNo){
  try{
    const userParam = encodeURIComponent(USER?.username || USER?.name || '');
    const res=await apiFetch(`/api/inventory/inspection_report_preview/${encodeURIComponent(orderNo)}?user_name=${userParam}`);
    if(!res.success){alert(res.message);return;}
    const d=res.report_data||{};
    const canMakeReport = Number(res.photo_count||0) > 0;
    let statusHtml = `<div style="margin:10px 0;padding:10px;border-radius:8px;background:${canMakeReport?'#E8FAF0':'#FFF0EF'}">검수용 사진: ${res.photo_count||0}장`;
    if(!canMakeReport){ statusHtml += `<br><b>작성 조건:</b> 검수조사서용 사진이 1장 이상 필요합니다.`; }
    else if((res.missing_photo_items||[]).length){ statusHtml += `<br><b>사진 누락 품목:</b> ${(res.missing_photo_items||[]).map(esc).join(', ')}<br><span style="color:#555">누락 품목이 있어도 사진이 1장 이상이면 XLSX 작성/다운로드는 가능합니다.</span>`; }
    statusHtml += '</div>';
    let html=statusHtml+'<div class="kv">';
    ['project_name','request_no','vendor_name','vendor_biz_no','vendor_ceo','vendor_address','inspection_date','inspection_place','inspection_result'].forEach(k=>{ html+=`<label>${k}</label><input data-rkey="${k}" value="${esc(d[k]||'')}">`; });
    html+='</div><br><b>품목</b><table id="insp-items" class="grid editable"><thead><tr><th>품명</th><th>규격</th><th>발주수량</th><th>납품수량</th><th>비고</th></tr></thead><tbody>';
    (d.items||[]).forEach(it=>{html+=`<tr><td contenteditable>${esc(it.item_name||'')}</td><td contenteditable>${esc(it.spec||'')}</td><td contenteditable>${esc(it.order_qty||'')}</td><td contenteditable>${esc(it.recv_qty||'')}</td><td contenteditable>${esc(it.note||'')}</td></tr>`});
    html+='</tbody></table>';
    html+=`<div id="inspection-photo-manager" style="margin-top:16px"></div>`;
    $('#insp-preview').innerHTML=html;
    await loadInspectionPhotos(orderNo);
  }catch(e){alert(e.message);}
}

async function loadInspectionPhotos(orderNo){
  const box = $('#inspection-photo-manager');
  if(!box) return;
  box.innerHTML = '<div style="padding:10px;color:#777">입고사진 목록을 불러오는 중입니다...</div>';
  try{
    const res = await apiFetch(`/api/inventory/inspection_photos/${encodeURIComponent(orderNo)}`);
    if(!res.success){ box.innerHTML = `<div class="alert error">${esc(res.message||'사진 목록을 불러올 수 없습니다.')}</div>`; return; }
    const rows = [];
    (res.items||[]).forEach(item=>{
      const photos = item.photos || [];
      if(!photos.length){
        rows.push({missing:true,item});
      }else{
        photos.forEach(p=>rows.push({missing:false,item,photo:p}));
      }
    });
    let html = `<div style="display:flex;gap:8px;align-items:center;margin:8px 0"><b>입고사진 목록</b><span style="color:#555;font-size:12px">업체: ${esc(res.vendor_name||'')} / 사진 ${res.photo_count||0}장</span>`;
    html += `<button type="button" class="btn light" id="insp-photo-refresh">사진 새로고침</button>`;
    html += `<button type="button" class="btn light" id="insp-photo-download-all">전체 다운로드</button></div>`;
    if(res.missing_items?.length){
      html += `<div style="margin:8px 0;padding:10px;border-radius:8px;background:#FFF0EF"><b>사진 누락 품목:</b> ${res.missing_items.map(esc).join(', ')}</div>`;
    }
    html += '<table class="grid" id="inspection-photo-table"><thead><tr><th>No.</th><th>품명</th><th>규격</th><th>사진구분</th><th>파일명</th><th>미리보기</th><th>사진 다운로드</th><th>품목 다운로드</th><th>사진 추가</th><th>삭제</th></tr></thead><tbody>';
    if(!rows.length){
      html += '<tr><td colspan="10" style="text-align:center;color:#777;padding:16px">등록된 입고사진이 없습니다.</td></tr>';
    }
    rows.forEach((r, idx)=>{
      const it = r.item || {};
      if(r.missing){
        html += `<tr data-item-id="${esc(it.item_id)}"><td>${idx+1}</td><td>${esc(it.item_name||'')}</td><td>${esc(it.spec||'')}</td><td colspan="3" style="color:#c0392b">사진 없음</td><td>-</td><td>-</td><td><button type="button" class="btn light insp-photo-upload">추가</button></td><td>-</td></tr>`;
        return;
      }
      const p = r.photo || {};
      const url = normUrl(p.url || '');
      const filename = p.filename || '';
      const category = p.category || '';
      html += `<tr data-item-id="${esc(it.item_id)}" data-filename="${esc(filename)}" data-category="${esc(category)}" data-url="${esc(url)}">`;
      html += `<td>${idx+1}</td><td>${esc(it.item_name||'')}</td><td>${esc(it.spec||'')}</td><td>${esc(category)}</td><td style="word-break:break-all">${esc(filename)}</td>`;
      html += `<td>${url?`<a href="${esc(url)}" target="_blank"><img src="${esc(url)}" style="width:80px;height:60px;object-fit:contain;background:#f5f5f5;border:1px solid #ddd;border-radius:6px"></a>`:''}</td>`;
      html += `<td><button type="button" class="btn light insp-photo-download">다운로드</button></td>`;
      html += `<td><button type="button" class="btn light insp-photo-download-item">품목 다운로드</button></td>`;
      html += `<td><button type="button" class="btn light insp-photo-upload">추가</button></td>`;
      html += `<td><button type="button" class="btn red insp-photo-delete">삭제</button></td>`;
      html += '</tr>';
    });
    html += '</tbody></table><input type="file" id="inspection-photo-file-input" accept="image/*" multiple style="display:none">';
    box.innerHTML = html;
    const refreshBtn = $('#insp-photo-refresh', box);
    if(refreshBtn) refreshBtn.onclick = ()=>loadInspectionPhotos(orderNo);
    const dlAll = $('#insp-photo-download-all', box);
    if(dlAll) dlAll.onclick = async()=>{
      const photoRows = $$('#inspection-photo-table tbody tr[data-url]', box).filter(tr=>tr.dataset.url);
      if(!photoRows.length){ alert('다운로드할 사진이 없습니다.'); return; }
      for(const tr of photoRows){
        try{ await downloadFile(tr.dataset.url); }catch(e){ console.warn(e); }
        await new Promise(r=>setTimeout(r, 150));
      }
    };
    $$('.insp-photo-download', box).forEach(btn=>{
      btn.onclick = async()=>{
        const tr = btn.closest('tr');
        if(tr?.dataset.url) await downloadFile(tr.dataset.url);
      };
    });
    $$('.insp-photo-download-item', box).forEach(btn=>{
      btn.onclick = async()=>{
        const tr = btn.closest('tr');
        const itemId = tr?.dataset.itemId || '';
        const itemRows = $$('#inspection-photo-table tbody tr[data-item-id]', box).filter(r=>String(r.dataset.itemId||'')===String(itemId) && r.dataset.url);
        if(!itemRows.length){ alert('해당 품목에 다운로드할 사진이 없습니다.'); return; }
        for(const r of itemRows){
          try{ await downloadFile(r.dataset.url); }catch(e){ console.warn(e); }
          await new Promise(res=>setTimeout(res, 150));
        }
      };
    });
    async function pickAndUploadPhoto(itemId, replace){
      if(!itemId){ alert('품목 정보를 찾을 수 없습니다.'); return; }
      const input = $('#inspection-photo-file-input', box);
      if(!input){ alert('파일 선택기를 만들지 못했습니다.'); return; }
      input.value = '';
      input.onchange = async()=>{
        const files = Array.from(input.files || []);
        if(!files.length) return;
        try{
          const fd = new FormData();
          fd.append('item_id', itemId);
          fd.append('category', '품질검수');
          fd.append('replace', replace ? '1' : '0');
          fd.append('user_name', USER?.name || USER?.username || '');
          files.forEach(f=>fd.append('photos', f));
          const res = await apiFetch('/api/inventory/inspection_photo', {method:'POST', body:fd});
          alert(res.message || (replace ? '사진을 교체했습니다.' : '사진을 추가했습니다.'));
          await loadReceipt();
          await loadInspectionPhotos(orderNo);
        }catch(e){ alert(e.message); }
      };
      input.click();
    }
    $$('.insp-photo-upload', box).forEach(btn=>{
      btn.onclick = async()=>{
        const tr = btn.closest('tr');
        await pickAndUploadPhoto(tr?.dataset.itemId || '', false);
      };
    });
    $$('.insp-photo-delete', box).forEach(btn=>{
      btn.onclick = async()=>{
        const tr = btn.closest('tr');
        const itemId = Number(tr?.dataset.itemId || 0);
        const filename = tr?.dataset.filename || '';
        const category = tr?.dataset.category || '';
        if(!itemId || !filename){ alert('삭제할 사진 정보를 찾을 수 없습니다.'); return; }
        if(!confirm(`사진을 삭제할까요?\n${filename}`)) return;
        try{
          const result = await apiFetch('/api/inventory/inspection_photo', {method:'DELETE', body:JSON.stringify({item_id:itemId, filename, category})});
          alert(result.message || '삭제되었습니다.');
          await loadReceipt();
          await loadInspectionPhotos(orderNo);
        }catch(e){ alert(e.message); }
      };
    });
  }catch(e){
    box.innerHTML = `<div class="alert error">${esc(e.message)}</div>`;
  }
}

async function createInspection(orderNo){
  const report_data={};
  $$('[data-rkey]').forEach(i=>report_data[i.dataset.rkey]=i.value);
  const itemRows=$$('#insp-items tbody tr');
  if(itemRows.length) report_data.items=itemRows.map(tr=>({item_name:tr.children[0].innerText,spec:tr.children[1].innerText,order_qty:tr.children[2].innerText,recv_qty:tr.children[3].innerText,note:tr.children[4].innerText}));
  try{
    const userParam = encodeURIComponent(USER?.username || USER?.name || '');
    const res=await apiFetch(`/api/inventory/inspection_report?user_name=${userParam}`,{method:'POST',body:JSON.stringify({order_no:orderNo, report_data})});
    if(!res.success){alert(res.message);return;}
    await downloadFile(normUrl(res.download_url));
    alert('검수조사서 XLSX 다운로드를 시작했습니다.');
    closeModal();
    loadReceipt();
  }catch(e){alert(e.message);}
}

async function openItemPhotos(itemId){
  try{
    const res=await apiFetch(`/api/inventory/item_photos/${encodeURIComponent(itemId)}`);
    if(!res.success){alert(res.message||'사진을 불러올 수 없습니다.');return;}
    const photos=res.photos||[];
    let html=`<p><b>${esc(res.item_name||'')}</b> ${esc(res.spec||'')}</p>`;
    if(!photos.length){ html+='<p>등록된 검수조사서용 사진이 없습니다.</p>'; }
    else{
      html+='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;max-height:70vh;overflow:auto">';
      photos.forEach(p=>{ const u=normUrl(p.url); html+=`<div style="border:1px solid #ddd;border-radius:10px;padding:8px;background:#fff"><div style="font-weight:700;margin-bottom:6px">${esc(p.category||'사진')}</div><a href="${esc(u)}" target="_blank"><img src="${esc(u)}" style="width:100%;height:150px;object-fit:contain;background:#f5f5f5;border-radius:8px"></a><div style="font-size:11px;color:#777;margin-top:6px;word-break:break-all">${esc(p.filename||'')}</div></div>`; });
      html+='</div>';
    }
    openModal('품목별 검수조사서용 사진', html, [['새 창으로 첫 사진 열기',()=>{ if(photos[0]?.url) window.open(normUrl(photos[0].url),'_blank'); }]]);
  }catch(e){alert(e.message);}
}

let deverpNgrokAutoStartTried = false;
let deverpNgrokPolling = false;

async function pollNgrokStatus(silent=false, maxTries=45){
  if(deverpNgrokPolling) return '';
  deverpNgrokPolling = true;
  const btn = document.getElementById('ngrok-start-btn');
  try{
    for(let i=0;i<maxTries;i++){
      const st = await apiFetch('/api/system/ngrok/status');
      const url = st.ngrok_url || st.public_mobile_base || '';
      const job = st.job || {};
      if(btn){
        if(url) btn.textContent = 'ngrok 갱신';
        else if((job.status||'') === 'failed') btn.textContent = 'ngrok 재시도';
        else btn.textContent = `ngrok 시작 중... ${i+1}/${maxTries}`;
      }
      if(url){
        await loadSettingsInfo(false);
        if(!silent) alert(`ngrok 주소가 적용되었습니다.\n${url}`);
        return url;
      }
      if((job.status||'') === 'failed'){
        const msg = job.message || st.ngrok_last_error || 'ngrok 시작 실패';
        await loadSettingsInfo(false);
        if(!silent) alert('ngrok 시작 실패: ' + msg);
        return '';
      }
      await new Promise(r=>setTimeout(r, 2000));
    }
    await loadSettingsInfo(false);
    if(!silent) alert('ngrok 주소를 아직 받지 못했습니다. 서버 PC의 logs/ngrok_tunnel.log 와 .runtime/ngrok_stdout.log를 확인하세요.');
    return '';
  }catch(e){
    if(!silent) alert('ngrok 상태 확인 실패: ' + e.message);
    return '';
  }finally{
    deverpNgrokPolling = false;
    if(btn){ btn.disabled = false; btn.textContent = 'ngrok 시작/갱신'; }
  }
}

async function startNgrokForMobile(silent=false){
  const btn = document.getElementById('ngrok-start-btn');
  const oldText = btn ? btn.textContent : '';
  if(btn){ btn.disabled = true; btn.textContent = '서버에서 ngrok 시작 요청...'; }
  try{
    const res = await apiFetch('/api/system/ngrok/start', {
      method: 'POST',
      body: JSON.stringify({regenerate_qr: true})
    });
    if(res.url){
      if(!silent) alert(`ngrok 주소가 적용되었습니다.\n${res.url}`);
      await loadSettingsInfo(false);
      return res.url;
    }
    if(res.success && res.starting){
      return await pollNgrokStatus(silent);
    }
    const msg = res.message || res.last_error || 'ngrok 시작 실패';
    if(!silent) alert(msg);
    return '';
  }catch(e){
    if(!silent) alert('ngrok 시작 요청 실패: ' + e.message);
    return '';
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = oldText || 'ngrok 시작/갱신'; }
  }
}

async function loadSettingsInfo(autoStart=true){
  try{
    const st = JSON.parse(localStorage.getItem('deverp_settings') || '{}');
    if($('#set-biz-id')) $('#set-biz-id').value = st.biz_id || '';
    if($('#set-biz-pw')) $('#set-biz-pw').value = st.biz_pw || '';
    if($('#set-bizbox-mode')) $('#set-bizbox-mode').value = st.bizbox_mode || 'client';
    const h=await apiFetch('/api/health');
    const qrUrl = h.qr_url || h.ngrok_url || h.public_mobile || '';
    const qrText = qrUrl || 'ngrok 주소 준비 중';
    const job = h.ngrok_job || {};
    const ngrokText = h.ngrok_active ? ' / ngrok 실행 중' : ((job.status === 'starting') ? ' / 서버 PC에서 ngrok 시작 중' : ((job.status === 'failed') ? ' / ngrok 실패' : ((h.use_ngrok || h.ngrok_required) ? ' / ngrok 대기 중' : ' / 내부망 주소')));
    const ngrokErr = (!h.ngrok_active && (job.message || h.ngrok_last_error)) ? `<p style="color:#c2410c;font-size:12px;margin-top:4px">ngrok 상태: ${esc(job.message || h.ngrok_last_error)}</p>` : '';
    $('#server-url-info').innerHTML=`<p>내부망 접속 주소: <b>${esc(h.web_url||location.origin)}</b></p><p>모바일/QR 접속 주소: <b>${esc(qrText)}</b><span style="color:#666">${esc(ngrokText)}</span> <button type="button" class="btn light" id="ngrok-start-btn" style="margin-left:8px">ngrok 시작/갱신</button></p>${ngrokErr}<p>클라이언트 자동화 에이전트: <b id="client-agent-status" class="client-agent-status">확인 중...</b> <button type="button" class="btn light client-agent-download" id="client-agent-download" style="display:none;margin-left:8px">EXE 자동설치 BAT 다운로드</button> <button type="button" class="btn light client-agent-exe-download" id="client-agent-exe-download" style="display:none;margin-left:4px">EXE 패키지 다운로드</button> <button type="button" class="btn light client-agent-refresh" style="margin-left:4px">프로세스 확인/갱신</button></p>`; deverpBindClientAgentPanelButtons();
    const ngrokBtn = document.getElementById('ngrok-start-btn');
    if(ngrokBtn) ngrokBtn.onclick = ()=>startNgrokForMobile(false);
    $('#qr-scan-link').href = qrUrl || '#';
    if(autoStart && (h.use_ngrok || h.ngrok_required) && !h.ngrok_active && !deverpNgrokAutoStartTried){
      deverpNgrokAutoStartTried = true;
      setTimeout(()=>startNgrokForMobile(true), 300);
    }
    deverpCheckClientAgentStatus();
  }catch(e){}
}
async function loadVendors(){ const q=$('#vendor-search')?.value||''; const data=await apiFetch('/api/purchase/vendors?query='+encodeURIComponent(q)); const tbody=$('#vendors-table tbody'); if(!tbody)return; tbody.innerHTML=''; data.forEach(v=>addVendorRow(v)); }
function vendorTableHtml(){ return `<div class="table-toolbar"><input id="vendor-search" placeholder="업체 검색" /><button class="btn light" onclick="loadVendors()">조회</button><button class="btn green" onclick="saveVendors()">저장</button><button class="btn light" onclick="addVendorRow()">+ 행 추가</button></div><div class="table-wrap" style="height:540px"><table id="vendors-table" class="grid editable copyable"><thead><tr><th>거래처명</th><th>대표자명</th><th>사업자등록번호</th><th>거래처담당자</th><th>핸드폰번호</th><th>담당자 E-MAIL</th><th>본사주소(기본)</th><th>비고</th></tr></thead><tbody></tbody></table></div>`; }
function addVendorRow(v={}){ const tbody=$('#vendors-table tbody'); if(!tbody)return; const map=[v.vendor_name||v.name||'', v.ceo||v.representative||'', v.biz_no||v.business_no||v.registration_no||'', v.contact_name||'', v.contact||v.phone||'', v.email||'', v.address||'', v.note||'']; const tr=document.createElement('tr'); map.forEach(x=>{const td=document.createElement('td'); td.contentEditable='true'; td.textContent=x; tr.appendChild(td);}); tr.onclick=()=>selectRow('vendors-table',tr); tbody.appendChild(tr); }
async function saveVendors(){ const vendors=$$('#vendors-table tbody tr').map(tr=>({ vendor_name:tr.children[0].innerText.trim(), ceo:tr.children[1].innerText.trim(), biz_no:tr.children[2].innerText.trim(), contact_name:tr.children[3].innerText.trim(), contact:tr.children[4].innerText.trim(), phone:tr.children[4].innerText.trim(), email:tr.children[5].innerText.trim(), address:tr.children[6].innerText.trim(), note:tr.children[7].innerText.trim() })).filter(v=>v.vendor_name); const res=await apiFetch('/api/purchase/vendors/save',{method:'POST',body:JSON.stringify({vendors})}); alert(res.message||'업체 정보가 저장되었습니다.'); }
$('#vendor-manage').onclick=async()=>{ openModal('업체관리', vendorTableHtml()); bindCopy('vendors-table'); await loadVendors(); };


$('#save-settings').onclick=()=>{
  const prev = JSON.parse(localStorage.getItem('deverp_settings') || '{}');
  localStorage.setItem('deverp_settings',JSON.stringify({
    ...prev,
    biz_id:$('#set-biz-id').value,
    biz_pw:$('#set-biz-pw').value,
    bizbox_mode:$('#set-bizbox-mode')?.value||'client'
  }));
  alert('설정 저장 완료'); loadSettingsInfo();
};

function openModal(title, body, actions=[]){ $('#modal-title').textContent=title; $('#modal-body').innerHTML=body; $('#modal-actions').innerHTML=''; actions.forEach(([txt,fn])=>{const b=document.createElement('button');b.className='btn blue';b.textContent=txt;b.onclick=fn;$('#modal-actions').appendChild(b);}); const close=document.createElement('button');close.className='btn light';close.textContent='닫기';close.onclick=closeModal;$('#modal-actions').appendChild(close); $('#modal').classList.remove('hidden'); }
function closeModal(){$('#modal').classList.add('hidden');}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function short(s,n){s=String(s||''); return s.length>n?s.slice(0,n)+'...':s;}
function normUrl(u){ if(!u) return ''; if(u.startsWith('/api/')) return u; if(u.startsWith('/inventory/')) return '/api'+u; if(u.startsWith('/purchase/')) return '/api'+u; return u; }
async function tryDownload(url){ try{ await downloadFile(url); }catch(e){} }
async function downloadFile(url){
  if(!url) return;
  const res=await fetch(url,{headers:authHeaders(false), cache:'no-store'});
  if(!res.ok) throw new Error('파일 다운로드 실패: '+url);
  const blob=await res.blob();
  let name='download';
  const cd=res.headers.get('content-disposition')||'';
  const m=cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
  if(m) name=decodeURIComponent(m[1]||m[2]); else name=url.split('/').pop() || 'download';
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download=name;
  a.rel='noopener';
  document.body.appendChild(a);
  a.click();
  setTimeout(()=>{ try{ URL.revokeObjectURL(a.href); }catch(e){} a.remove(); }, 3000);
}

function deverpDirectDownload(url, filename){
  if(!url) return false;
  const finalUrl = url + (url.includes('?') ? '&' : '?') + 't=' + Date.now();
  try{
    const a=document.createElement('a');
    a.href=finalUrl;
    if(filename) a.download=filename;
    a.rel='noopener';
    a.target='_blank';
    document.body.appendChild(a);
    a.click();
    setTimeout(()=>a.remove(), 1000);
    return true;
  }catch(e){
    try{ window.open(finalUrl, '_blank'); return true; }catch(_e){}
  }
  return false;
}

const DEVERP_CLIENT_AGENT_URL = 'http://127.0.0.1:8765';

async function deverpCallClientAgent(path, payload, timeoutMs=5000){
  const ctrl = new AbortController();
  const timer = setTimeout(()=>ctrl.abort(), timeoutMs);
  try{
    const res = await fetch(DEVERP_CLIENT_AGENT_URL + path, {
      method:'POST',
      mode:'cors',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload || {}),
      signal:ctrl.signal
    });
    if(!res.ok){
      const parsed = await deverpReadResponseJsonOrText(res);
      throw new Error(deverpResponseMessage(parsed, `Client Agent HTTP ${res.status}`));
    }
    return await res.json();
  }catch(e){
    if(e.name === 'AbortError') throw new Error('클라이언트 자동화 에이전트 연결 시간이 초과되었습니다. 웹 접속 PC에서 다운로드한 install_client_agent_to_Documents_autorun.bat을 관리자 권한으로 1회 실행했는지 확인하세요. v35부터는 BAT가 내부망 서버 주소로 EXE ZIP을 먼저 다운로드하고, 현재 Windows 사용자 내문서에 압축 해제한 뒤 로그인 자동실행을 등록합니다. 클라이언트 PC에 Python은 필요 없습니다.');
    if(String(e.message||'').includes('Failed to fetch')) throw new Error('클라이언트 자동화 에이전트가 실행 중이 아닙니다. 웹 접속 PC에서 다운로드한 install_client_agent_to_Documents_autorun.bat을 관리자 권한으로 1회 실행하세요. v35부터는 BAT가 내부망 서버 주소로 EXE ZIP을 먼저 다운로드하고, 현재 Windows 사용자 내문서에 압축 해제한 뒤 로그인 자동실행을 등록합니다. 클라이언트 PC에 Python은 필요 없습니다.');
    throw e;
  }finally{
    clearTimeout(timer);
  }
}

async function deverpRunClientPurchaseAutomation(job, settings){
  await deverpEnsureClientAgentVersionFresh();
  const r = await deverpCallClientAgent('/bizbox/purchase_request', {
    bizbox_id: settings.biz_id || '',
    bizbox_pw: settings.biz_pw || '',
    server_base: job.server_base || location.origin,
    token: TOKEN || '',
    request_data: job.request_data || {},
    attachment_urls: job.attachment_urls || [],
    poll_interval_seconds: 10
  }, 120000);
  if(!r.success){
    throw new Error(r.message || r.result?.message || '클라이언트 PC Bizbox 구매의뢰 자동화가 실패했습니다.');
  }
  return r;
}

async function deverpRunClientOrderMailAutomation(mailJobs, settings, serverBase){
  if(!mailJobs || !mailJobs.length) throw new Error('메일 자동작성 작업이 없습니다. 발주서/업체 정보를 확인하세요.');
  await deverpEnsureClientAgentVersionFresh();
  const r = await deverpCallClientAgent('/bizbox/order_mail', {
    bizbox_id: settings.biz_id || '',
    bizbox_pw: settings.biz_pw || '',
    server_base: serverBase || location.origin,
    token: TOKEN || '',
    mail_jobs: mailJobs || [],
    poll_interval_seconds: 10
  }, 120000);
  if(!r.success){
    throw new Error(r.message || r.result?.message || '클라이언트 PC Bizbox 메일 자동화가 실패했습니다.');
  }
  return r;
}


const DEVERP_CLIENT_AGENT_CHECK_INTERVAL_MS = 30000;
let __deverpClientAgentInfo = null;
let __deverpClientAgentCheckerStarted = false;

async function deverpGetClientAgentServerInfo(){
  if(__deverpClientAgentInfo) return __deverpClientAgentInfo;
  try{
    __deverpClientAgentInfo = await apiFetch('/api/system/client_agent/status');
  }catch(e){
    __deverpClientAgentInfo = {version:'client-agent-unknown', setup_url:'/api/system/client_agent/setup_bat', exe_url:'/api/system/client_agent/exe'};
  }
  return __deverpClientAgentInfo;
}

function deverpSetClientAgentStatus(text, color){
  const els = Array.from(document.querySelectorAll('#client-agent-status, .client-agent-status'));
  if(!els.length) return;
  els.forEach(el=>{
    el.textContent = text;
    if(color) el.style.color = color;
  });
}

function deverpBindClientAgentPanelButtons(){
  document.querySelectorAll('#client-agent-download, .client-agent-download').forEach(btn=>{
    btn.onclick = (ev)=>{ ev.preventDefault(); deverpDownloadClientAgentSetup(true); };
  });
  document.querySelectorAll('#client-agent-exe-download, .client-agent-exe-download').forEach(btn=>{
    btn.onclick = (ev)=>{ ev.preventDefault(); deverpDownloadClientAgentExe(true); };
  });
  document.querySelectorAll('.client-agent-refresh').forEach(btn=>{
    btn.onclick = (ev)=>{ ev.preventDefault(); __deverpClientAgentInfo=null; deverpCheckClientAgentStatus({autoDownload:false, background:false, manual:true}); };
  });
}

function deverpShowClientAgentDownloadButton(show, info=null){
  deverpBindClientAgentPanelButtons();
  document.querySelectorAll('#client-agent-download, .client-agent-download').forEach(btn=>{
    btn.style.display = show ? '' : 'none';
  });
  document.querySelectorAll('#client-agent-exe-download, .client-agent-exe-download').forEach(btn=>{
    const available = !info || info.exe_available !== false;
    btn.style.display = (show && available) ? '' : 'none';
    if(info && info.exe_available === false) btn.title = '서버 PC에서 build.bat 재빌드 후 EXE가 생성되면 다운로드할 수 있습니다.';
  });
}

function deverpEnsureFixedClientAgentPanel(){
  const sidebar = document.querySelector('.sidebar');
  if(!sidebar || document.getElementById('client-agent-fixed-panel')) return;
  const panel = document.createElement('div');
  panel.id = 'client-agent-fixed-panel';
  panel.style.cssText = 'position:absolute;left:12px;right:12px;bottom:72px;border:1px solid rgba(255,255,255,.25);border-radius:10px;padding:10px;background:rgba(255,255,255,.08);color:#fff;font-size:12px;z-index:10;';
  panel.innerHTML = '<div style="font-weight:700;margin-bottom:8px">클라이언트 에이전트</div>' +
    '<div style="margin-bottom:8px"><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#9ca3af;margin-right:6px"></span><span class="client-agent-status">프로세스 확인 중...</span></div>' +
    '<button type="button" class="btn light client-agent-download" style="padding:7px 10px;margin:0 4px 4px 0;font-size:12px;display:none">EXE 자동설치</button>' +
    '<button type="button" class="btn light client-agent-exe-download" style="padding:7px 10px;margin:0 4px 4px 0;font-size:12px;display:none">EXE ZIP</button>' +
    '<button type="button" class="btn light client-agent-refresh" style="padding:7px 10px;margin:0;font-size:12px">갱신</button>';
  sidebar.appendChild(panel);
  deverpBindClientAgentPanelButtons();
}

async function deverpDownloadClientAgentSetup(force=false){
  const info = await deverpGetClientAgentServerInfo();
  const version = info.version || 'client-agent';
  const key = 'deverp_client_agent_setup_downloaded_' + version;
  if(force){
    localStorage.removeItem(key);
  }else if(localStorage.getItem(key) === '1'){
    deverpShowClientAgentDownloadButton(true, info);
    return false;
  }
  const setupUrl = (info && info.setup_url) ? info.setup_url : '/api/system/client_agent/setup_bat';
  try{
    const ok = deverpDirectDownload(setupUrl, (info && info.setup_filename) ? info.setup_filename : 'install_client_agent_to_Documents_autorun.bat');
    if(!ok) throw new Error('브라우저 다운로드 호출 실패');
    localStorage.setItem(key, '1');
    localStorage.setItem('deverp_client_agent_setup_downloaded_at', String(Date.now()));
    deverpSetClientAgentStatus('설치/업데이트 BAT 다운로드 요청됨. 받은 BAT을 1회 실행하세요.', '#ffcc66');
    deverpShowClientAgentDownloadButton(true, info);
    return true;
  }catch(e){
    deverpSetClientAgentStatus('미실행 - 설치파일 다운로드 실패: ' + (e.message || e), '#ff8080');
    deverpShowClientAgentDownloadButton(true, info);
    return false;
  }
}


async function deverpDownloadClientAgentExe(force=false){
  const info = await deverpGetClientAgentServerInfo();
  if(info && info.exe_available === false){
    alert('서버에 DevERP_Client_Agent.exe 패키지가 아직 없습니다. 서버 PC에서 build.bat을 다시 실행한 뒤 다운로드하세요.');
    return false;
  }
  const exeUrl = (info && info.exe_url) ? info.exe_url : '/api/system/client_agent/exe';
  try{
    const ok = deverpDirectDownload(exeUrl, (info && info.exe_filename) ? info.exe_filename : 'DevERP_Client_Agent_EXE_Package.zip');
    if(!ok) throw new Error('브라우저 다운로드 호출 실패');
    return true;
  }catch(e){
    alert('클라이언트 에이전트 EXE 패키지 다운로드 실패: ' + (e.message || e));
    return false;
  }
}

function deverpFormatClientAgentHealth(j){
  const parts = [];
  if(j.version) parts.push(j.version);
  if(j.pid) parts.push('PID ' + j.pid);
  if(j.process_name) parts.push(j.process_name);
  if(j.frozen === true) parts.push('EXE');
  else if(j.frozen === false) parts.push('Python');
  return '실행 중' + (parts.length ? ' (' + parts.join(' / ') + ')' : '');
}

async function deverpConfigureClientAgentNotifications(info=null){
  try{
    info = info || await deverpGetClientAgentServerInfo();
    await deverpCallClientAgent('/notifications/configure', {
      server_base: (info && (info.server_lan_base || info.server_base)) || location.origin,
      server_base_fallback: (info && info.server_base) || location.origin,
      poll_interval_seconds: 10
    }, 3000);
  }catch(e){
    // 구버전 에이전트나 일시 연결 실패는 상태 표시/자동화 흐름을 막지 않는다.
  }
}

async function deverpEnsureClientAgentVersionFresh(){
  let info = null;
  try{ info = await deverpGetClientAgentServerInfo(); }catch(e){ info = null; }
  if(!info || !info.version) return true;
  try{
    const ctrl = new AbortController();
    const timer = setTimeout(()=>ctrl.abort(), 1500);
    const res = await fetch(DEVERP_CLIENT_AGENT_URL + '/health', {mode:'cors', signal:ctrl.signal});
    clearTimeout(timer);
    if(!res.ok) return true;
    const j = await res.json().catch(()=>({}));
    if(j.version && j.version !== info.version){
      try{ await deverpDownloadClientAgentSetup(true); }catch(e){}
      throw new Error('클라이언트 에이전트가 이전 버전입니다.\n현재 실행 중: ' + j.version + '\n서버 최신: ' + info.version + '\n방금 다운로드된 install_client_agent_to_Documents_autorun.bat을 현재 Windows 사용자로 실행한 뒤 다시 결재상신하세요.');
    }
  }catch(e){
    if(String(e.message || '').includes('이전 버전')) throw e;
  }
  return true;
}

async function deverpCheckClientAgentStatus(opts={}){
  const settings = JSON.parse(localStorage.getItem('deverp_settings') || '{}');
  const mode = (settings.bizbox_mode || 'client').toLowerCase();
  const el = document.getElementById('client-agent-status') || document.querySelector('.client-agent-status');
  if(!el && !opts.background) return false;
  let info = null;
  try{ info = await deverpGetClientAgentServerInfo(); }catch(e){}
  if(mode !== 'client'){
    deverpSetClientAgentStatus('서버 PC 실행 모드', '#555');
    deverpShowClientAgentDownloadButton(false, info);
    return true;
  }
  try{
    const ctrl = new AbortController();
    const timer = setTimeout(()=>ctrl.abort(), 1200);
    const res = await fetch(DEVERP_CLIENT_AGENT_URL + '/health', {mode:'cors', signal:ctrl.signal});
    clearTimeout(timer);
    if(res.ok){
      const j = await res.json().catch(()=>({}));
      if(info && info.version && j.version && info.version !== j.version){
        deverpSetClientAgentStatus('실행 중(구버전) - 현재 ' + j.version + ' / 서버 ' + info.version + ' / 업데이트 BAT 실행 필요', '#b06b00');
        deverpShowClientAgentDownloadButton(true, info);
        if(opts.autoDownload){
          await deverpDownloadClientAgentSetup(true);
        }
        return false;
      }
      deverpSetClientAgentStatus(deverpFormatClientAgentHealth(j), '#0a7f28');
      deverpShowClientAgentDownloadButton(false, info);
      deverpConfigureClientAgentNotifications(info);
      if(j.version) localStorage.setItem('deverp_client_agent_running_version', j.version);
      if(j.pid) localStorage.setItem('deverp_client_agent_pid', String(j.pid));
      if(j.executable) localStorage.setItem('deverp_client_agent_executable', j.executable);
      return true;
    }
    throw new Error('agent response not ok');
  }catch(e){
    const version = (info && info.version) || 'client-agent';
    const key = 'deverp_client_agent_setup_downloaded_' + version;
    const alreadyDownloaded = localStorage.getItem(key) === '1';
    if(alreadyDownloaded){
      deverpSetClientAgentStatus('미실행 - 로컬 프로세스 없음. 다운로드한 BAT를 다시 실행하세요.', '#b06b00');
      deverpShowClientAgentDownloadButton(true, info);
      return false;
    }
    deverpSetClientAgentStatus('미실행 - 로컬 프로세스 없음. 내부망 EXE 자동설치 BAT 실행 필요', '#b00020');
    deverpShowClientAgentDownloadButton(true, info);
    if(opts.autoDownload){
      await deverpDownloadClientAgentSetup(false);
    }
    return false;
  }
}

function deverpStartClientAgentChecker(){
  if(__deverpClientAgentCheckerStarted) return;
  __deverpClientAgentCheckerStarted = true;
  // 웹 진입 직후 1회 확인한다. 미설치이면 내부망 EXE 자동설치를 한 번만 다운로드한다.
  setTimeout(()=>deverpCheckClientAgentStatus({autoDownload:true, background:true}), 1000);
  // 이후에는 30초마다 상태만 확인한다. 반복 다운로드는 하지 않는다.
  setInterval(()=>deverpCheckClientAgentStatus({autoDownload:false, background:true}), DEVERP_CLIENT_AGENT_CHECK_INTERVAL_MS);
}

document.addEventListener('DOMContentLoaded',()=>{ if(TOKEN&&USER) showApp(); else showLogin(); deverpEnsureFixedClientAgentPanel(); loadSettingsInfo(); deverpBindClientAgentPanelButtons(); deverpStartClientAgentChecker(); });


// MARK_SUBMITTED_FORCE_FIX_20260509

/* ─────────────────────────────────────────────
   PATCH 20260509-3: 구매의뢰 제목/추천업체 표시 + Excel 복사 + 발주검색
   ───────────────────────────────────────────── */
(function(){
  if(window.__DEVERP_UI_EXCEL_VENDOR_FIX_V3__) return;
  window.__DEVERP_UI_EXCEL_VENDOR_FIX_V3__ = true;

  const qs = (s, root=document) => root.querySelector(s);
  const qsa = (s, root=document) => Array.from(root.querySelectorAll(s));

  function clean(v){
    return String(v || '').replace(/\r?\n+/g, ' ').replace(/\t/g, ' ').replace(/\s{2,}/g, ' ').trim();
  }

  function stripBracketTitle(s){
    return clean(String(s || '').replace(/\[[^\]]*\]\s*/g, ' ')) || '-';
  }

  function copyPlainText(text, label){
    text = String(text || '');
    if(!text.trim()){
      alert('복사할 내용이 없습니다.');
      return;
    }

    const done = () => alert((label || '표') + ' 내용을 복사했습니다. Excel에 바로 붙여넣으세요.');

    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();

    let ok = false;
    try{ ok = document.execCommand('copy'); }catch(e){ ok = false; }
    ta.remove();

    if(ok){
      done();
      return;
    }

    if(navigator.clipboard){
      navigator.clipboard.writeText(text).then(done).catch(()=>{
        prompt('자동 복사가 차단되었습니다. 아래 내용을 Ctrl+C로 복사하세요.', text);
      });
    }else{
      prompt('자동 복사가 차단되었습니다. 아래 내용을 Ctrl+C로 복사하세요.', text);
    }
  }

  function cellValue(cell){
    const clone = cell.cloneNode(true);
    clone.querySelectorAll('button, .no-copy, script, style').forEach(x=>x.remove());
    clone.querySelectorAll('input').forEach(input=>{
      let txt = '';
      if(input.type === 'checkbox' || input.type === 'radio') txt = input.checked ? 'Y' : '';
      else txt = input.value || '';
      input.replaceWith(document.createTextNode(txt));
    });
    clone.querySelectorAll('textarea, select').forEach(el=>{
      el.replaceWith(document.createTextNode(el.value || el.innerText || ''));
    });
    return clean(clone.innerText || clone.textContent || '');
  }

  function tableToTSV(tableId, onlyVisible=true){
    const table = document.getElementById(tableId);
    if(!table) return '';

    const rows = [];
    if(table.tHead) rows.push(...Array.from(table.tHead.rows));
    Array.from(table.tBodies || []).forEach(tb=>rows.push(...Array.from(tb.rows)));

    return rows.filter(tr=>{
      if(!onlyVisible) return true;
      const st = getComputedStyle(tr);
      return st.display !== 'none' && st.visibility !== 'hidden';
    }).map(tr=>{
      return Array.from(tr.children).filter(cell=>{
        const st = getComputedStyle(cell);
        return st.display !== 'none' && st.visibility !== 'hidden';
      }).map(cellValue).join('\t');
    }).filter(line=>clean(line)).join('\n');
  }

  function copyTableExcel(tableId, label){
    copyPlainText(tableToTSV(tableId), label || tableId);
  }

  function getFinalTitle(){
    return clean(qs('#pr-title-full-edit')?.value || qs('#pr-title-preview')?.textContent || '');
  }

  function getPurchasePurpose(){
    return clean(qs('#pr-purpose-edit')?.value || stripBracketTitle(getFinalTitle()));
  }

  function syncFinalTitleAndPurpose(force=false){
    const preview = clean(qs('#pr-title-preview')?.textContent || '');
    const final = qs('#pr-title-full-edit');
    const purpose = qs('#pr-purpose-edit');
    if(final && (force || final.dataset.manual !== '1')){
      if(preview && preview !== '제목 입력 시 자동으로 채워집니다. 필요 시 수정 가능합니다.'){
        final.value = preview;
      }
    }
    if(purpose && (force || purpose.dataset.manual !== '1')){
      purpose.value = stripBracketTitle(final?.value || preview);
    }
  }

  function purchaseFullTSV(){
    const rows = [];
    const get = id => clean(qs('#'+id)?.value || qs('#'+id)?.textContent || '');

    rows.push('항목\t내용');
    rows.push('정부과제코드\t' + get('pr-project-code'));
    rows.push('항목\t' + get('pr-category'));
    rows.push('세세목\t' + get('pr-sub-category'));
    rows.push('구분\t' + get('pr-item-type'));
    rows.push('구매 제목\t' + get('pr-title-main'));
    rows.push('구매의뢰 제목\t' + get('pr-title-full-edit'));
    rows.push('구매목적\t' + get('pr-purpose-edit'));
    rows.push('실제 프로젝트\t' + get('pr-project-name'));
    rows.push('요청자\t' + get('pr-requester'));
    rows.push('부서\t' + get('pr-department'));
    rows.push('납기일\t' + get('pr-required-date'));
    rows.push('구매의뢰서 번호\t' + get('custom-request-no'));

    rows.push('');
    rows.push('[품목표]');
    rows.push(tableToTSV('pr-items', false));

    if(qs('#actual-box') && !qs('#actual-box').classList.contains('hidden')){
      rows.push('');
      rows.push('[실제 입고 품목표]');
      rows.push(tableToTSV('actual-items', false));
    }

    rows.push('');
    rows.push('[추천업체]');
    rows.push(tableToTSV('pr-vendors', false));

    return rows.join('\n');
  }

  function copyPurchaseRequestExcel(){
    syncFinalTitleAndPurpose(false);
    copyPlainText(purchaseFullTSV(), '구매의뢰서');
  }

  function addPrVendorRow(v={}){
    const tbody = qs('#pr-vendors tbody');
    if(!tbody) return;
    const tr = document.createElement('tr');
    tr.dataset.vendorIndex = v.vendor_index ?? tbody.children.length;
    tr.dataset.ceo = v.ceo || v.representative || '';
    tr.dataset.bizNo = v.biz_no || v.business_no || v.registration_no || '';
    tr.dataset.address = v.address || '';
    tr.dataset.phone = v.phone || '';
    tr.dataset.contactName = v.contact_name || '';
    const vals = [
      tbody.children.length + 1,
      v.name || v.vendor_name || '',
      v.reason || '',
      v.contact || v.phone || '',
      v.email || '',
      v.fax || ''
    ];
    vals.forEach((val, i)=>{
      const td = document.createElement('td');
      td.innerText = val || '';
      if(i > 0) td.contentEditable = 'true';
      tr.appendChild(td);
    });
    tr.onclick = () => {
      qsa('#pr-vendors tbody tr').forEach(r=>r.classList.remove('selected'));
      tr.classList.add('selected');
    };
    tbody.appendChild(tr);
  }

  function clearAndRenderPrVendors(vendors){
    const tbody = qs('#pr-vendors tbody');
    if(!tbody) return;
    tbody.innerHTML = '';
    (vendors || []).forEach(v=>addPrVendorRow(v));
    if(!tbody.children.length) addPrVendorRow({});
  }

  async function lookupVendor(v){
    const name = clean(v.name || v.vendor_name || '');
    if(!name) return v;
    try{
      const info = await apiFetch('/api/purchase/vendor_lookup?name=' + encodeURIComponent(name));
      const out = Object.assign({}, v);
      out.name = info.name || info.vendor_name || name;
      out.vendor_name = out.name;
      out.reason = v.reason || '';
      out.contact = v.contact || info.contact || info.phone || '';
      out.phone = v.phone || info.phone || info.contact || '';
      out.contact_name = v.contact_name || info.contact_name || '';
      out.email = v.email || info.email || '';
      out.fax = v.fax || info.fax || '';
      out.ceo = v.ceo || info.ceo || info.representative || '';
      out.biz_no = v.biz_no || info.biz_no || info.business_no || info.registration_no || '';
      out.address = v.address || info.address || '';
      return out;
    }catch(e){
      return v;
    }
  }

  async function refreshPrVendorInfo(force=false){
    let vendors = getPurchaseVendorsForSubmit([]);
    if(!vendors.length && window.parsedVendors) vendors = parsedVendors;
    const out = [];
    for(const v of vendors){
      out.push(await lookupVendor(v));
    }
    if(window.parsedVendors) parsedVendors = out;
    clearAndRenderPrVendors(out);
  }

  function getPurchaseVendorsForSubmit(items=[]){
    const rows = qsa('#pr-vendors tbody tr');
    let vendors = rows.map((tr, idx)=>{
      const c = tr.children;
      const name = clean(c[1]?.innerText || '');
      return {
        name,
        vendor_name: name,
        reason: clean(c[2]?.innerText || ''),
        contact: clean(c[3]?.innerText || ''),
        email: clean(c[4]?.innerText || ''),
        fax: clean(c[5]?.innerText || ''),
        vendor_index: tr.dataset.vendorIndex === '' ? idx : Number(tr.dataset.vendorIndex ?? idx),
        ceo: tr.dataset.ceo || '',
        biz_no: tr.dataset.bizNo || '',
        address: tr.dataset.address || '',
        phone: tr.dataset.phone || '',
        contact_name: tr.dataset.contactName || ''
      };
    }).filter(v=>v.name);

    if(!vendors.length && window.parsedVendors && parsedVendors.length) vendors = parsedVendors;
    if(!vendors.length && typeof uniqueVendorsFromItems === 'function') vendors = uniqueVendorsFromItems(items || []);
    return vendors;
  }

  function filterOrdersTable(){
    const q = clean(qs('#orders-search')?.value || '').toLowerCase();
    qsa('#orders-table tbody tr').forEach(tr=>{
      const hay = clean(tr.innerText).toLowerCase();
      tr.style.display = (!q || hay.includes(q)) ? '' : 'none';
    });
  }

  function bindOnce(el, ev, fn, key){
    if(!el || el.dataset[key] === '1') return;
    el.dataset[key] = '1';
    el.addEventListener(ev, fn);
  }

  function ensureButtonsAndEvents(){
    bindOnce(qs('#copy-purchase-full'), 'click', copyPurchaseRequestExcel, 'boundCopy');
    bindOnce(qs('#copy-pr-items'), 'click', ()=>copyTableExcel('pr-items', '구매의뢰 품목표'), 'boundCopy');
    bindOnce(qs('#copy-actual-items'), 'click', ()=>copyTableExcel('actual-items', '실제 입고 품목표'), 'boundCopy');
    bindOnce(qs('#copy-orders-table'), 'click', ()=>copyTableExcel('orders-table', '발주 관리'), 'boundCopy');
    bindOnce(qs('#copy-receipt-table'), 'click', ()=>copyTableExcel('receipt-table', '입고 관리'), 'boundCopy');
    bindOnce(qs('#copy-pr-vendors'), 'click', ()=>copyTableExcel('pr-vendors', '추천업체'), 'boundCopy');
    bindOnce(qs('#add-pr-vendor'), 'click', ()=>addPrVendorRow({}), 'boundVendor');
    bindOnce(qs('#del-pr-vendor'), 'click', ()=>{
      const tbody = qs('#pr-vendors tbody');
      if(!tbody) return;
      const selected = qsa('#pr-vendors tbody tr.selected');
      (selected.length ? selected : [tbody.lastElementChild]).forEach(tr=>tr && tr.remove());
      qsa('#pr-vendors tbody tr').forEach((tr,i)=>tr.children[0].innerText=i+1);
      if(!tbody.children.length) addPrVendorRow({});
    }, 'boundVendor');
    bindOnce(qs('#refresh-pr-vendor'), 'click', ()=>refreshPrVendorInfo(true), 'boundVendor');
    bindOnce(qs('#orders-search'), 'input', filterOrdersTable, 'boundSearch');

    const final = qs('#pr-title-full-edit');
    const purpose = qs('#pr-purpose-edit');
    bindOnce(final, 'input', ()=>{
      final.dataset.manual = '1';
      if(purpose && purpose.dataset.manual !== '1') purpose.value = stripBracketTitle(final.value);
    }, 'boundTitle');
    bindOnce(purpose, 'input', ()=>{ purpose.dataset.manual = '1'; }, 'boundPurpose');

    ['pr-project-code','pr-category','pr-sub-category','pr-item-type','pr-title-main'].forEach(id=>{
      const el = qs('#'+id);
      bindOnce(el, 'input', ()=>setTimeout(()=>syncFinalTitleAndPurpose(false), 0), 'boundTitleSync');
    });

    if(qs('#pr-vendors tbody') && !qs('#pr-vendors tbody').children.length){
      clearAndRenderPrVendors(window.parsedVendors || []);
    }

    syncFinalTitleAndPurpose(false);
  }

  if(typeof updateTitlePreview === 'function' && !updateTitlePreview.__finalTitleWrappedV3){
    const oldUpdateTitlePreview = updateTitlePreview;
    updateTitlePreview = function(){
      const r = oldUpdateTitlePreview.apply(this, arguments);
      setTimeout(()=>syncFinalTitleAndPurpose(false), 0);
      return r;
    };
    updateTitlePreview.__finalTitleWrappedV3 = true;
  }

  if(typeof loadOrders === 'function' && !loadOrders.__orderSearchWrappedV3){
    const oldLoadOrders = loadOrders;
    loadOrders = async function(){
      const r = await oldLoadOrders.apply(this, arguments);
      setTimeout(filterOrdersTable, 0);
      return r;
    };
    loadOrders.__orderSearchWrappedV3 = true;
  }

  let lastParsedVendorSig = '';
  async function syncParsedVendors(){
    if(!window.parsedVendors) return;
    const sig = JSON.stringify(parsedVendors.map(v=>[v.name||v.vendor_name||'', v.email||'', v.contact||'', v.fax||'']));
    if(sig === lastParsedVendorSig) return;
    lastParsedVendorSig = sig;
    if(parsedVendors.length){
      const out = [];
      for(const v of parsedVendors) out.push(await lookupVendor(v));
      parsedVendors = out;
      clearAndRenderPrVendors(out);
    }
  }

  document.addEventListener('DOMContentLoaded', ensureButtonsAndEvents);
  setInterval(()=>{
    ensureButtonsAndEvents();
    filterOrdersTable();
    syncParsedVendors();
  }, 1000);

  window.copyTableExcel = copyTableExcel;
  window.copyPurchaseRequestExcel = copyPurchaseRequestExcel;
  window.getPurchasePurpose = getPurchasePurpose;
  window.getFinalTitle = getFinalTitle;
  window.getPurchaseVendorsForSubmit = getPurchaseVendorsForSubmit;
  window.refreshPrVendorInfo = refreshPrVendorInfo;
})();

/* ─────────────────────────────────────────────
   PATCH 20260509-4: 복사 버튼 제거 + 표 Shift/Ctrl 다중선택 복사
   ───────────────────────────────────────────── */
(function(){
  if(window.__DEVERP_TABLE_MULTISELECT_COPY_V4__) return;
  window.__DEVERP_TABLE_MULTISELECT_COPY_V4__ = true;

  const TABLE_IDS = [
    'pr-items',
    'actual-items',
    'pr-vendors',
    'orders-table',
    'receipt-table',
    'dashboard-orders',
    'vendors-table'
  ];

  let activeCopyTable = null;
  const anchorRowIndex = new WeakMap();

  function qs(s, root=document){ return root.querySelector(s); }
  function qsa(s, root=document){ return Array.from(root.querySelectorAll(s)); }

  function cleanText(v){
    return String(v || '')
      .replace(/\r?\n+/g, ' ')
      .replace(/\t/g, ' ')
      .replace(/\s{2,}/g, ' ')
      .trim();
  }

  function removeCopyButtons(){
    [
      'copy-purchase-full',
      'copy-pr-items',
      'copy-actual-items',
      'copy-pr-vendors',
      'copy-pr-vendors-fix',
      'copy-orders-table',
      'copy-receipt-table',
      'copy-dashboard-orders',
      'copy-vendors-table'
    ].forEach(id => {
      const el = document.getElementById(id);
      if(el) el.remove();
    });

    qsa('button').forEach(btn=>{
      const t = cleanText(btn.innerText || btn.textContent || '');
      if(t.includes('엑셀복사') || t.includes('품목표 복사') || t.includes('실제입고표 복사')){
        btn.remove();
      }
    });
  }

  function ensureStyle(){
    if(document.getElementById('table-multiselect-copy-style')) return;
    const st = document.createElement('style');
    st.id = 'table-multiselect-copy-style';
    st.textContent = `
      table.grid tbody tr.copy-row-selected,
      table.grid tbody tr.selected.copy-row-selected {
        outline: 2px solid #2563eb !important;
        background: #dbeafe !important;
      }
      table.grid.copy-active {
        box-shadow: 0 0 0 2px rgba(37,99,235,.25);
      }
    `;
    document.head.appendChild(st);
  }

  function cellText(cell){
    const clone = cell.cloneNode(true);
    clone.querySelectorAll('button, .no-copy, script, style').forEach(x=>x.remove());

    clone.querySelectorAll('input').forEach(input=>{
      let txt = '';
      if(input.type === 'checkbox' || input.type === 'radio'){
        txt = input.checked ? 'Y' : '';
      }else{
        txt = input.value || '';
      }
      input.replaceWith(document.createTextNode(txt));
    });

    clone.querySelectorAll('textarea, select').forEach(el=>{
      el.replaceWith(document.createTextNode(el.value || el.innerText || ''));
    });

    return cleanText(clone.innerText || clone.textContent || '');
  }

  function visibleRows(table){
    return qsa('tbody tr', table).filter(tr=>{
      const st = getComputedStyle(tr);
      return st.display !== 'none' && st.visibility !== 'hidden';
    });
  }

  function selectedRows(table){
    return qsa('tbody tr.copy-row-selected', table).filter(tr=>{
      const st = getComputedStyle(tr);
      return st.display !== 'none' && st.visibility !== 'hidden';
    });
  }

  function headerLine(table){
    const headRow = table.tHead ? table.tHead.rows[0] : null;
    if(!headRow) return '';
    return Array.from(headRow.children).map(cellText).join('\t');
  }

  function rowLine(tr){
    return Array.from(tr.children).map(cellText).join('\t');
  }

  function tableSelectionToTSV(table){
    const headers = headerLine(table);
    const rows = selectedRows(table);
    const source = rows.length ? rows : visibleRows(table);
    const body = source.map(rowLine).filter(x=>cleanText(x)).join('\n');

    if(headers && body) return headers + '\n' + body;
    if(headers) return headers;
    return body;
  }

  function copyText(text){
    if(!cleanText(text)){
      alert('복사할 표 내용이 없습니다.');
      return;
    }

    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();

    let ok = false;
    try{ ok = document.execCommand('copy'); }catch(e){ ok = false; }
    ta.remove();

    if(ok){
      console.log('DevERP table copied to clipboard');
      return;
    }

    if(navigator.clipboard){
      navigator.clipboard.writeText(text).catch(()=>{
        prompt('자동 복사가 차단되었습니다. 아래 내용을 Ctrl+C로 복사하세요.', text);
      });
    }else{
      prompt('자동 복사가 차단되었습니다. 아래 내용을 Ctrl+C로 복사하세요.', text);
    }
  }

  function clearTableSelection(table){
    qsa('tbody tr.copy-row-selected', table).forEach(tr=>tr.classList.remove('copy-row-selected'));
  }

  function setActiveTable(table){
    if(activeCopyTable && activeCopyTable !== table){
      activeCopyTable.classList.remove('copy-active');
    }
    activeCopyTable = table;
    table.classList.add('copy-active');
    table.tabIndex = 0;
    try{ table.focus({preventScroll:true}); }catch(e){ table.focus(); }
  }

  function selectRange(table, fromIndex, toIndex){
    const rows = visibleRows(table);
    const a = Math.max(0, Math.min(fromIndex, toIndex));
    const b = Math.min(rows.length - 1, Math.max(fromIndex, toIndex));
    for(let i=a; i<=b; i++){
      rows[i]?.classList.add('copy-row-selected');
    }
  }

  function bindTable(table){
    if(!table || table.dataset.multiCopyBound === '1') return;
    table.dataset.multiCopyBound = '1';
    table.tabIndex = 0;

    table.addEventListener('click', ev=>{
      const tr = ev.target.closest('tbody tr');
      if(!tr || !table.contains(tr)) return;

      setActiveTable(table);

      const rows = visibleRows(table);
      const idx = rows.indexOf(tr);
      if(idx < 0) return;

      const isMultiKey = ev.ctrlKey || ev.metaKey;
      const isShift = ev.shiftKey;

      if(isShift){
        const anchor = anchorRowIndex.get(table);
        if(anchor === undefined || anchor === null){
          if(!isMultiKey) clearTableSelection(table);
          tr.classList.add('copy-row-selected');
          anchorRowIndex.set(table, idx);
        }else{
          if(!isMultiKey) clearTableSelection(table);
          selectRange(table, anchor, idx);
        }
      }else if(isMultiKey){
        tr.classList.toggle('copy-row-selected');
        anchorRowIndex.set(table, idx);
      }else{
        clearTableSelection(table);
        tr.classList.add('copy-row-selected');
        anchorRowIndex.set(table, idx);
      }

      if(typeof selectRow === 'function'){
        try{ selectRow(table.id, tr); }catch(e){}
      }
    });

    table.addEventListener('keydown', ev=>{
      if((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'c'){
        ev.preventDefault();
        setActiveTable(table);
        copyText(tableSelectionToTSV(table));
      }

      if((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'a'){
        ev.preventDefault();
        clearTableSelection(table);
        visibleRows(table).forEach(tr=>tr.classList.add('copy-row-selected'));
        setActiveTable(table);
      }

      if(ev.key === 'Escape'){
        clearTableSelection(table);
      }
    });
  }

  function bindAllTables(){
    ensureStyle();
    removeCopyButtons();

    TABLE_IDS.forEach(id=>{
      const table = document.getElementById(id);
      if(table) bindTable(table);
    });
  }

  document.addEventListener('keydown', ev=>{
    if((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'c'){
      const tag = (document.activeElement?.tagName || '').toLowerCase();

      if(['input','textarea'].includes(tag)) return;

      const table = document.activeElement?.closest?.('table.grid') || activeCopyTable;
      if(table && TABLE_IDS.includes(table.id)){
        ev.preventDefault();
        copyText(tableSelectionToTSV(table));
      }
    }
  }, true);

  window.copyTable = function(table){
    if(!table) table = activeCopyTable;
    if(table) copyText(tableSelectionToTSV(table));
  };

  document.addEventListener('DOMContentLoaded', bindAllTables);
  setInterval(bindAllTables, 1000);
})();

/* ─────────────────────────────────────────────
   PATCH 20260509-5: 견적서 업체 → 업체관리 정보 → 추천업체표/결재상신 자동반영
   ───────────────────────────────────────────── */

function deverpCleanText(v){
  return String(v || '')
    .replace(/\r?\n+/g, ' ')
    .replace(/\t/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function deverpStripBracketTitle(s){
  return deverpCleanText(String(s || '').replace(/\[[^\]]*\]\s*/g, ' ')) || '-';
}

function deverpGetFinalTitle(){
  return deverpCleanText(
    document.getElementById('pr-title-full-edit')?.value ||
    document.getElementById('pr-title-preview')?.textContent ||
    ''
  );
}

function deverpGetPurchasePurpose(){
  const manual = deverpCleanText(document.getElementById('pr-purpose-edit')?.value || '');
  if(manual) return manual;
  return deverpStripBracketTitle(deverpGetFinalTitle());
}

function deverpSyncTitlePurpose(force=false){
  const preview = deverpCleanText(document.getElementById('pr-title-preview')?.textContent || '');
  const finalEl = document.getElementById('pr-title-full-edit');
  const purposeEl = document.getElementById('pr-purpose-edit');

  if(finalEl && (force || finalEl.dataset.manual !== '1')){
    if(preview && preview !== '제목 입력 시 자동으로 채워집니다. 필요 시 수정 가능합니다.'){
      finalEl.value = preview;
    }
  }

  if(purposeEl && (force || purposeEl.dataset.manual !== '1')){
    purposeEl.value = deverpStripBracketTitle(finalEl?.value || preview);
  }
}

async function deverpLookupVendorInfo(v){
  const name = deverpCleanText(v.name || v.vendor_name || v.vendor || '');
  if(!name) return v;

  try{
    const info = await apiFetch('/api/purchase/vendor_lookup?name=' + encodeURIComponent(name));
    const out = Object.assign({}, v);

    out.name = info.name || info.vendor_name || name;
    out.vendor_name = out.name;

    // 사용자가 이미 입력한 값은 우선 보존, 비어 있으면 업체관리 정보로 보강
    out.reason = v.reason || '';
    out.contact_name = v.contact_name || info.contact_name || '';
    out.phone = v.phone || info.phone || info.contact || '';
    out.contact = v.contact || [out.contact_name, out.phone].filter(Boolean).join(' / ') || info.contact || '';
    out.email = v.email || info.email || '';
    out.fax = v.fax || info.fax || '';
    out.ceo = v.ceo || info.ceo || info.representative || '';
    out.biz_no = v.biz_no || info.biz_no || info.business_no || info.registration_no || '';
    out.address = v.address || info.address || '';
    out.category = v.category || info.category || '';
    out.sub_category = v.sub_category || info.sub_category || '';
    return out;
  }catch(e){
    return v;
  }
}

function deverpEnsureVendorTable(){
  const table = document.getElementById('pr-vendors');
  if(!table) return null;
  return table.querySelector('tbody');
}

function deverpAddVendorRow(v={}){
  const tbody = deverpEnsureVendorTable();
  if(!tbody) return;

  const tr = document.createElement('tr');
  tr.dataset.vendorIndex = v.vendor_index ?? tbody.children.length;
  tr.dataset.ceo = v.ceo || '';
  tr.dataset.bizNo = v.biz_no || v.business_no || v.registration_no || '';
  tr.dataset.address = v.address || '';
  tr.dataset.phone = v.phone || '';
  tr.dataset.contactName = v.contact_name || '';

  const vals = [
    tbody.children.length + 1,
    v.name || v.vendor_name || '',
    v.reason || '',
    v.contact || v.phone || '',
    v.email || '',
    v.fax || ''
  ];

  vals.forEach((val, i)=>{
    const td = document.createElement('td');
    td.innerText = val || '';
    if(i > 0) td.contentEditable = 'true';
    tr.appendChild(td);
  });

  tr.onclick = () => {
    document.querySelectorAll('#pr-vendors tbody tr').forEach(r=>r.classList.remove('selected'));
    tr.classList.add('selected');
  };

  tbody.appendChild(tr);
}

function deverpRenderVendorTable(vendors){
  const tbody = deverpEnsureVendorTable();
  if(!tbody) return;

  tbody.innerHTML = '';

  const src = vendors && vendors.length ? vendors : [];
  src.forEach(v => deverpAddVendorRow(v));

  if(!tbody.children.length){
    deverpAddVendorRow({});
  }
}


function deverpVendorKeyForMerge(name){
  return String(name || '').toLowerCase().replace(/[^0-9a-z가-힣]/g, '');
}

function deverpMergeVendorListsForSubmit(base=[], extra=[]){
  const out = [];
  const hasVendor = (name)=>{
    const key = deverpVendorKeyForMerge(name);
    if(!key) return false;
    return out.some(v=>{
      const vk = deverpVendorKeyForMerge(v.name || v.vendor_name || v.vendor || '');
      return vk && (vk === key || vk.includes(key) || key.includes(vk));
    });
  };
  const pushVendor = (v, fallbackIndex)=>{
    if(!v) return;
    const name = String(v.name || v.vendor_name || v.vendor || v.company || '').trim();
    if(!name || hasVendor(name)) return;
    out.push(deverpNormalizeVendorForSubmit(Object.assign({}, v, {
      name,
      vendor_name: name,
      vendor_index: (v.vendor_index === undefined || v.vendor_index === null || v.vendor_index === '') ? fallbackIndex : v.vendor_index,
      reason: v.reason || '기존거래업체'
    }), fallbackIndex));
  };
  (base || []).forEach((v,i)=>pushVendor(v,i));
  (extra || []).forEach((v,i)=>pushVendor(v,out.length));
  return out;
}
function deverpReadVendorTable(items=[]){
  const rows = Array.from(document.querySelectorAll('#pr-vendors tbody tr'));
  let vendors = rows.map((tr, idx)=>{
    const c = tr.children;
    const name = deverpCleanText(c[1]?.innerText || '');
    return {
      name,
      vendor_name: name,
      reason: deverpCleanText(c[2]?.innerText || ''),
      contact: deverpCleanText(c[3]?.innerText || ''),
      email: deverpCleanText(c[4]?.innerText || ''),
      fax: deverpCleanText(c[5]?.innerText || ''),
      vendor_index: tr.dataset.vendorIndex === '' ? idx : Number(tr.dataset.vendorIndex ?? idx),
      ceo: tr.dataset.ceo || '',
      biz_no: tr.dataset.bizNo || '',
      address: tr.dataset.address || '',
      phone: tr.dataset.phone || '',
      contact_name: tr.dataset.contactName || ''
    };
  }).filter(v => v.name);

  // 추천업체 표가 기존 행만 갖고 있어도 견적서 자동인식 결과와 품목의 업체명을 항상 병합한다.
  // 이 보정이 없으면 뉴스타/두성자동화처럼 인식은 되었지만 표에 누락된 업체가
  // 발주 관리/입고 관리로 넘어가지 않을 수 있다.
  if(typeof parsedVendors !== 'undefined' && Array.isArray(parsedVendors) && parsedVendors.length){
    vendors = deverpMergeVendorListsForSubmit(vendors, parsedVendors);
  }

  if(typeof uniqueVendorsFromItems === 'function'){
    vendors = deverpMergeVendorListsForSubmit(vendors, uniqueVendorsFromItems(items || []));
  }

  return vendors;
}

async function deverpRefreshVendorTableFromParsed(){
  if(typeof parsedVendors === 'undefined') return;

  const base = parsedVendors && parsedVendors.length ? parsedVendors : deverpReadVendorTable([]);
  const enriched = [];
  for(const v of base){
    enriched.push(await deverpLookupVendorInfo(v));
  }

  parsedVendors = enriched;
  deverpRenderVendorTable(enriched);
}

function deverpBindVendorButtons(){
  const addBtn = document.getElementById('add-pr-vendor');
  if(addBtn && addBtn.dataset.deverpBound !== '1'){
    addBtn.dataset.deverpBound = '1';
    addBtn.onclick = () => deverpAddVendorRow({});
  }

  const delBtn = document.getElementById('del-pr-vendor');
  if(delBtn && delBtn.dataset.deverpBound !== '1'){
    delBtn.dataset.deverpBound = '1';
    delBtn.onclick = () => {
      const tbody = deverpEnsureVendorTable();
      if(!tbody) return;
      const selected = Array.from(tbody.querySelectorAll('tr.selected'));
      (selected.length ? selected : [tbody.lastElementChild]).forEach(tr=>tr && tr.remove());
      Array.from(tbody.children).forEach((tr,i)=>tr.children[0].innerText=i+1);
      if(!tbody.children.length) deverpAddVendorRow({});
    };
  }

  const refreshBtn = document.getElementById('refresh-pr-vendor');
  if(refreshBtn && refreshBtn.dataset.deverpBound !== '1'){
    refreshBtn.dataset.deverpBound = '1';
    refreshBtn.onclick = () => deverpRefreshVendorTableFromParsed();
  }

  const finalEl = document.getElementById('pr-title-full-edit');
  if(finalEl && finalEl.dataset.deverpBound !== '1'){
    finalEl.dataset.deverpBound = '1';
    finalEl.addEventListener('input', ()=>{
      finalEl.dataset.manual = '1';
      const purposeEl = document.getElementById('pr-purpose-edit');
      if(purposeEl && purposeEl.dataset.manual !== '1'){
        purposeEl.value = deverpStripBracketTitle(finalEl.value);
      }
    });
  }

  const purposeEl = document.getElementById('pr-purpose-edit');
  if(purposeEl && purposeEl.dataset.deverpBound !== '1'){
    purposeEl.dataset.deverpBound = '1';
    purposeEl.addEventListener('input', ()=>{ purposeEl.dataset.manual = '1'; });
  }
}

// 기존 제목 미리보기 함수와 연결
if(typeof updateTitlePreview === 'function' && !updateTitlePreview.__deverpPurposeWrap){
  const _oldUpdateTitlePreview = updateTitlePreview;
  updateTitlePreview = function(){
    const r = _oldUpdateTitlePreview.apply(this, arguments);
    setTimeout(()=>deverpSyncTitlePurpose(false), 0);
    return r;
  };
  updateTitlePreview.__deverpPurposeWrap = true;
}

// 견적서 인식 fetch 완료 후 parsedVendors 변경을 감지해 자동조회
let __deverpVendorSig = '';
async function deverpWatchParsedVendors(){
  if(typeof parsedVendors === 'undefined') return;
  const sig = JSON.stringify(parsedVendors.map(v=>[
    v.name || v.vendor_name || '',
    v.email || '',
    v.contact || '',
    v.fax || ''
  ]));

  if(sig && sig !== __deverpVendorSig){
    __deverpVendorSig = sig;
    if(parsedVendors.length){
      await deverpRefreshVendorTableFromParsed();
    }
  }
}

document.addEventListener('DOMContentLoaded', ()=>{
  deverpBindVendorButtons();
  deverpSyncTitlePurpose(true);
  if(deverpEnsureVendorTable() && !deverpEnsureVendorTable().children.length){
    deverpRenderVendorTable(typeof parsedVendors !== 'undefined' ? parsedVendors : []);
  }
});

setInterval(()=>{
  deverpBindVendorButtons();
  deverpSyncTitlePurpose(false);
  deverpWatchParsedVendors();
}, 800);

// createPurchase가 payload를 만들기 직전에 사용하도록 전역 제공
window.getPurchaseVendorsForSubmit = deverpReadVendorTable;
window.getPurchasePurpose = deverpGetPurchasePurpose;
window.getFinalTitle = deverpGetFinalTitle;

/* ─────────────────────────────────────────────
   PATCH 20260509-6: 추천사유 기본값 / Bizbox 계정검증 / 선행작업 검증
   ───────────────────────────────────────────── */

function deverpDefaultVendorReason(v){
  v = v || {};
  if(!String(v.reason || '').trim()) v.reason = '기존거래업체';
  return v;
}

function deverpNormalizeVendorForSubmit(v, idx){
  v = deverpDefaultVendorReason(Object.assign({}, v || {}));
  v.name = v.name || v.vendor_name || v.vendor || '';
  v.vendor_name = v.vendor_name || v.name || '';
  if(v.vendor_index === undefined || v.vendor_index === null || v.vendor_index === '') v.vendor_index = idx || 0;
  return v;
}

function deverpEnsureVendorReasonUI(){
  const rows = Array.from(document.querySelectorAll('#pr-vendors tbody tr'));
  rows.forEach(tr=>{
    const reasonCell = tr.children[2];
    if(reasonCell && !String(reasonCell.innerText || '').trim()){
      reasonCell.innerText = '기존거래업체';
    }
  });

  if(typeof parsedVendors !== 'undefined' && Array.isArray(parsedVendors)){
    parsedVendors = parsedVendors.map((v, i)=>deverpNormalizeVendorForSubmit(v, i));
  }
}

function deverpBizboxSettings(){
  try{
    return JSON.parse(localStorage.getItem('deverp_settings') || '{}') || {};
  }catch(e){
    return {};
  }
}

function deverpHasBizboxAccount(){
  const st = deverpBizboxSettings();
  return !!(String(st.biz_id || '').trim() && String(st.biz_pw || '').trim());
}

function deverpShowBizboxAccountRequired(){
  alert('Bizbox 결재계정 아이디/비밀번호가 입력되어 있지 않습니다.\n설정 > 계정정보에서 Bizbox 아이디와 비밀번호를 먼저 입력해주세요.');
  try{
    if(typeof navigate === 'function') navigate('settings');
    setTimeout(()=>{
      document.getElementById('set-biz-id')?.focus();
    }, 200);
  }catch(e){}
}

function deverpOrderSendDoneStatus(order){
  const st = String(order?.status || '').trim();
  return ['발주서전송완료', '발주서전송', '발주진행완료', '입고대기', '입고완료', '완료'].includes(st);
}

function deverpBindValidationButtons(){
  const submitBtn = document.getElementById('pr-submit');
  if(submitBtn && submitBtn.dataset.deverpValidationBound !== '1'){
    submitBtn.dataset.deverpValidationBound = '1';
    submitBtn.onclick = async()=>{
      if(!deverpHasBizboxAccount()){
        deverpShowBizboxAccountRequired();
        return;
      }
      deverpEnsureVendorReasonUI();
      if(typeof createPurchase === 'function') await createPurchase(false);
    };
  }

  const completeBtn = document.getElementById('pr-complete');
  if(completeBtn && completeBtn.dataset.deverpValidationBound !== '1'){
    completeBtn.dataset.deverpValidationBound = '1';
    completeBtn.onclick = async()=>{
      if(!currentRequestId){
        alert('상신완료는 결재상신 후 처리할 수 있습니다.\n먼저 [결재 상신]을 진행해주세요.');
        return;
      }
      deverpEnsureVendorReasonUI();
      if(typeof createPurchase === 'function') await createPurchase(true);
    };
  }

  const sendBtn = document.getElementById('send-order');
  if(sendBtn && sendBtn.dataset.deverpValidationBound !== '1'){
    sendBtn.dataset.deverpValidationBound = '1';
    const oldSend = sendBtn.onclick;
    sendBtn.onclick = async function(ev){
      if(!selectedOrderId){
        alert('발주 건을 선택하세요.');
        return;
      }
      if(!deverpHasBizboxAccount()){
        deverpShowBizboxAccountRequired();
        return;
      }

      if(typeof oldSend === 'function'){
        const r = await oldSend.call(this, ev);
        try{
          if(selectedOrder) selectedOrder.status = '발주서전송완료';
        }catch(e){}
        return r;
      }
    };
  }

  const orderCompleteBtn = document.getElementById('order-complete');
  if(orderCompleteBtn && orderCompleteBtn.dataset.deverpValidationBound !== '1'){
    orderCompleteBtn.dataset.deverpValidationBound = '1';
    const oldComplete = orderCompleteBtn.onclick;
    orderCompleteBtn.onclick = async function(ev){
      if(!selectedOrderId){
        alert('발주 건을 선택하세요.');
        return;
      }

      if(selectedOrder && !deverpOrderSendDoneStatus(selectedOrder)){
        alert('발주진행완료는 발주서 전송 후 처리할 수 있습니다.\n먼저 [발주서 전송]을 진행해주세요.');
        return;
      }

      if(typeof oldComplete === 'function'){
        const r = await oldComplete.call(this, ev);
        return r;
      }
    };
  }
}

// 기존 getPurchaseVendorsForSubmit이 있으면 감싸서 추천사유 기본값 보정
if(typeof getPurchaseVendorsForSubmit === 'function' && !getPurchaseVendorsForSubmit.__reasonDefaultWrapped){
  const _oldGetPurchaseVendorsForSubmit = getPurchaseVendorsForSubmit;
  getPurchaseVendorsForSubmit = function(items){
    const vendors = _oldGetPurchaseVendorsForSubmit.apply(this, arguments) || [];
    return vendors.map((v, i)=>deverpNormalizeVendorForSubmit(v, i));
  };
  getPurchaseVendorsForSubmit.__reasonDefaultWrapped = true;
}else if(typeof getPurchaseVendorsForSubmit !== 'function'){
  window.getPurchaseVendorsForSubmit = function(items){
    let vendors = [];
    try{
      const rows = Array.from(document.querySelectorAll('#pr-vendors tbody tr'));
      vendors = rows.map((tr, idx)=>{
        const c = tr.children;
        const name = String(c[1]?.innerText || '').trim();
        return deverpNormalizeVendorForSubmit({
          name,
          vendor_name: name,
          reason: String(c[2]?.innerText || '').trim(),
          contact: String(c[3]?.innerText || '').trim(),
          email: String(c[4]?.innerText || '').trim(),
          fax: String(c[5]?.innerText || '').trim(),
          vendor_index: tr.dataset.vendorIndex === '' ? idx : Number(tr.dataset.vendorIndex ?? idx),
          ceo: tr.dataset.ceo || '',
          biz_no: tr.dataset.bizNo || '',
          address: tr.dataset.address || '',
          phone: tr.dataset.phone || '',
          contact_name: tr.dataset.contactName || ''
        }, idx);
      }).filter(v=>v.name);
    }catch(e){}

    if(!vendors.length && typeof parsedVendors !== 'undefined' && Array.isArray(parsedVendors)){
      vendors = parsedVendors.map((v, i)=>deverpNormalizeVendorForSubmit(v, i));
    }

    if(!vendors.length && typeof uniqueVendorsFromItems === 'function'){
      vendors = uniqueVendorsFromItems(items || []).map((v, i)=>deverpNormalizeVendorForSubmit(v, i));
    }

    return vendors;
  };
}

// createPurchase 직전에도 추천사유 기본값 보정
if(typeof createPurchase === 'function' && !createPurchase.__reasonDefaultWrapped){
  const _oldCreatePurchase = createPurchase;
  createPurchase = async function(markComplete){
    deverpEnsureVendorReasonUI();
    return await _oldCreatePurchase.apply(this, arguments);
  };
  createPurchase.__reasonDefaultWrapped = true;
}

// 업체 자동인식 후에도 계속 보정
document.addEventListener('DOMContentLoaded', ()=>{
  deverpBindValidationButtons();
  deverpEnsureVendorReasonUI();
});

setInterval(()=>{
  deverpBindValidationButtons();
  deverpEnsureVendorReasonUI();
}, 800);

/* ─────────────────────────────────────────────
   PATCH 20260509-7: 설정탭 비밀번호 변경 UI 동작
   ───────────────────────────────────────────── */
(function(){
  if(window.__DEVERP_PASSWORD_CHANGE_PATCH__) return;
  window.__DEVERP_PASSWORD_CHANGE_PATCH__ = true;

  async function changeMyPassword(){
    const current = document.getElementById('set-current-pw')?.value || '';
    const next = document.getElementById('set-new-pw')?.value || '';
    const confirm = document.getElementById('set-new-pw-confirm')?.value || '';

    if(!current){
      alert('현재 비밀번호를 입력하세요.');
      document.getElementById('set-current-pw')?.focus();
      return;
    }
    if(!next){
      alert('새 비밀번호를 입력하세요.');
      document.getElementById('set-new-pw')?.focus();
      return;
    }
    if(next !== confirm){
      alert('새 비밀번호와 확인값이 일치하지 않습니다.');
      document.getElementById('set-new-pw-confirm')?.focus();
      return;
    }

    try{
      const res = await apiFetch('/api/users/change_password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: current,
          new_password: next
        })
      });

      alert(res.message || '비밀번호가 변경되었습니다. 다시 로그인해주세요.');

      document.getElementById('set-current-pw').value = '';
      document.getElementById('set-new-pw').value = '';
      document.getElementById('set-new-pw-confirm').value = '';

      localStorage.removeItem('deverp_token');
      localStorage.removeItem('deverp_user');
      TOKEN = '';
      USER = null;
      showLogin();
    }catch(e){
      alert(e.message || '비밀번호 변경 실패');
    }
  }

  function bindPasswordButton(){
    const btn = document.getElementById('change-password');
    if(btn && btn.dataset.bound !== '1'){
      btn.dataset.bound = '1';
      btn.onclick = changeMyPassword;
    }
  }

  document.addEventListener('DOMContentLoaded', bindPasswordButton);
  setInterval(bindPasswordButton, 1000);
})();


/* ─────────────────────────────────────────────
   MATERIAL_BUDGET_PATCH_20260520
   정부과제/연차/구분 드롭다운 + 재료비관리 엑셀 연동
   ───────────────────────────────────────────── */
(function(){
  if(window.__DEVERP_MATERIAL_BUDGET_PATCH_20260520__) return;
  window.__DEVERP_MATERIAL_BUDGET_PATCH_20260520__ = true;

  let materialBudgetData = {projects:[], years_by_project:{}, types_by_project_year:{}, rows:[]};
  let materialBudgetLoading = false;

  const qs = (s, root=document)=>root.querySelector(s);
  const qsa = (s, root=document)=>Array.from(root.querySelectorAll(s));
  const clean = v => String(v || '').replace(/\r?\n+/g, ' ').replace(/\t/g, ' ').replace(/\s{2,}/g, ' ').trim();
  const num = v => Number(String(v ?? '').replace(/[^0-9.\-]/g, '')) || 0;
  const money = v => Math.round(num(v)).toLocaleString('ko-KR');

  function setOptions(sel, values, placeholder){
    if(!sel) return;
    const old = sel.value;
    sel.innerHTML = '';
    const opt0 = document.createElement('option');
    opt0.value = '';
    opt0.textContent = placeholder || '선택';
    sel.appendChild(opt0);
    (values || []).forEach(v=>{
      if(!clean(v)) return;
      const opt = document.createElement('option');
      opt.value = clean(v);
      opt.textContent = clean(v);
      sel.appendChild(opt);
    });
    if(old && (values || []).map(clean).includes(old)) sel.value = old;
  }

  function projectSeq(yearText){
    const m = String(yearText || '').match(/(\d+)\s*차/);
    return m ? String(parseInt(m[1], 10)).padStart(2, '0') : '';
  }

  function composeProjectCode(){
    const base = clean(qs('#pr-project-base')?.value).toUpperCase();
    const year = clean(qs('#pr-project-year')?.value);
    const seq = projectSeq(year);
    const code = base && seq ? `${base}_${seq}` : base;
    const el = qs('#pr-project-code');
    if(el && el.value !== code){
      el.value = code;
      el.dispatchEvent(new Event('input', {bubbles:true}));
    }
    return code;
  }

  function itemTotalAmount(){
    try{
      if(typeof getItems === 'function'){
        return (getItems('pr-items') || []).reduce((s, it)=>s + (num(it.amount) || (num(it.unit_price) * (num(it.quantity) || 1))), 0);
      }
    }catch(e){}
    let total = 0;
    qsa('#pr-items tbody tr').forEach(tr=>{
      const price = num(tr.children[3]?.innerText || '0');
      const qty = num(tr.children[4]?.innerText || '0');
      total += price * qty;
    });
    return total;
  }

  function findSelectedBudgetRow(){
    const project = clean(qs('#pr-project-base')?.value).toUpperCase();
    const year = clean(qs('#pr-project-year')?.value);
    const type = clean(qs('#pr-item-type')?.value);
    return (materialBudgetData.rows || []).find(r =>
      clean(r.project_code).toUpperCase() === project &&
      clean(r.project_year) === year &&
      clean(r.budget_type) === type
    );
  }

  function renderBudgetStatus(){
    const box = qs('#pr-budget-status');
    if(!box) return;
    const row = findSelectedBudgetRow();
    box.classList.remove('ok', 'warn', 'bad');
    if(!clean(qs('#pr-project-base')?.value) || !clean(qs('#pr-project-year')?.value) || !clean(qs('#pr-item-type')?.value)){
      box.textContent = '정부과제, 연차, 구분을 선택하면 재료비관리 엑셀 기준 배정액·사용액·잔액이 표시됩니다. 사용액/잔액은 상신완료 건만 반영됩니다.';
      return;
    }
    if(!row){
      box.textContent = '선택한 정부과제/연차/구분의 재료비 예산을 찾지 못했습니다. [재료비관리]에서 엑셀 내용을 확인하세요.';
      box.classList.add('warn');
      return;
    }
    const req = itemTotalAmount();
    const remaining = num(row.remaining_amount);
    const after = remaining - req;
    box.innerHTML = `배정액 <b>${money(row.budget_amount)}원</b> / 사용액 <b>${money(row.used_amount)}원</b> / 현재 잔액 <b>${money(row.remaining_amount)}원</b> / 이번 의뢰금액 <b>${money(req)}원</b> / 상신완료 시 잔액 <b>${money(after)}원</b>`;
    box.classList.add(after < 0 ? 'bad' : (remaining <= 0 ? 'warn' : 'ok'));
  }

  function refreshDependentDropdowns(){
    composeProjectCode();
    const project = clean(qs('#pr-project-base')?.value).toUpperCase();
    const years = materialBudgetData.years_by_project?.[project] || [];
    setOptions(qs('#pr-project-year'), years, '연차 선택');
    composeProjectCode();
    const year = clean(qs('#pr-project-year')?.value);
    const key = `${project}||${year}`;
    setOptions(qs('#pr-item-type'), materialBudgetData.types_by_project_year?.[key] || [], '구분 선택');
    renderBudgetStatus();
    if(typeof updateTitlePreview === 'function') updateTitlePreview();
  }

  function refreshTypeDropdown(){
    composeProjectCode();
    const project = clean(qs('#pr-project-base')?.value).toUpperCase();
    const year = clean(qs('#pr-project-year')?.value);
    const key = `${project}||${year}`;
    setOptions(qs('#pr-item-type'), materialBudgetData.types_by_project_year?.[key] || [], '구분 선택');
    renderBudgetStatus();
    if(typeof updateTitlePreview === 'function') updateTitlePreview();
  }

  async function loadMaterialBudget(){
    if(materialBudgetLoading) return materialBudgetData;
    materialBudgetLoading = true;
    try{
      const data = await apiFetch('/api/purchase/material_budget');
      materialBudgetData = data || materialBudgetData;
      setOptions(qs('#pr-project-base'), materialBudgetData.projects || [], '과제코드');
      refreshDependentDropdowns();
      return materialBudgetData;
    }catch(e){
      console.warn('재료비관리 로드 실패:', e);
      const box = qs('#pr-budget-status');
      if(box){ box.textContent = '재료비관리 엑셀 정보를 불러오지 못했습니다: ' + e.message; box.classList.add('bad'); }
      return materialBudgetData;
    }finally{
      materialBudgetLoading = false;
    }
  }

  let materialBudgetCurrentProject = '';

  function materialProjectFromForm(){
    return clean(qs('#pr-project-base')?.value).toUpperCase();
  }

  function getMaterialProjectFilter(){
    return clean(qs('#material-project-filter')?.value || materialBudgetCurrentProject).toUpperCase();
  }

  function setMaterialProjectFilterOptions(){
    const sel = qs('#material-project-filter');
    if(!sel) return;
    const projects = (materialBudgetData.projects || []).map(v=>clean(v).toUpperCase()).filter(Boolean);
    const preferred = getMaterialProjectFilter() || materialProjectFromForm() || projects[0] || '';
    sel.innerHTML = '';
    const opt0 = document.createElement('option');
    opt0.value = '';
    opt0.textContent = '과제코드 선택';
    sel.appendChild(opt0);
    projects.forEach(p=>{
      const opt = document.createElement('option');
      opt.value = p;
      opt.textContent = p;
      sel.appendChild(opt);
    });
    if(preferred && projects.includes(preferred)){
      sel.value = preferred;
      materialBudgetCurrentProject = preferred;
    }else{
      materialBudgetCurrentProject = '';
    }
  }

  function materialBudgetVisibleRows(){
    const project = getMaterialProjectFilter();
    if(!project) return materialBudgetData.rows || [];
    return (materialBudgetData.rows || []).filter(r=>clean(r.project_code).toUpperCase() === project);
  }

  function materialBudgetTableHtml(){
    return `<div class="table-toolbar">
      <label class="small-info" style="display:flex;align-items:center;gap:8px;margin:0">과제코드
        <select id="material-project-filter" style="min-width:160px"><option value="">과제코드 선택</option></select>
      </label>
      <button class="btn light" type="button" id="material-add-row">+ 행 추가</button>
      <button class="btn light" type="button" id="material-del-row">행 삭제</button>
      <button class="btn green" type="button" id="material-save">저장</button>
      <button class="btn light" type="button" id="material-refresh">다시조회</button>
    </div>
    <p class="small-info">과제코드별로 분리해 표시합니다. 과제코드는 엑셀 시트명, 구매연도는 연차, 구분/구매비용은 예산 기준입니다. 사용금액은 직접 수정 가능하며, 미수정 행은 구매의뢰 DB의 상신완료 건 기준으로 자동 계산되어 엑셀에도 저장됩니다.</p>
    <div class="material-summary" id="material-summary"></div>
    <div class="table-wrap" style="height:560px"><table id="material-budget-table" class="grid editable copyable"><thead><tr>
      <th>정부과제코드</th><th>구매연도</th><th>구분</th><th>구매비용(원)</th><th>사용금액(원)</th><th>잔액(원)</th>
    </tr></thead><tbody></tbody></table></div>`;
  }

  function addMaterialRow(row={}){
    const tbody = qs('#material-budget-table tbody');
    if(!tbody) return;
    const tr = document.createElement('tr');
    const defaultProject = getMaterialProjectFilter() || materialProjectFromForm();
    const budgetVal = num(row.budget_amount || 0);
    const usedVal = num(row.used_amount || 0);
    const remainVal = ('remaining_amount' in row) ? num(row.remaining_amount || 0) : (budgetVal - usedVal);
    const vals = [row.project_code || defaultProject || '', row.project_year || '', row.budget_type || '', money(budgetVal), money(usedVal), money(remainVal)];
    tr.dataset.manualUsedAmount = (row.manual_used_amount !== undefined && row.manual_used_amount !== null && String(row.manual_used_amount) !== '') ? String(row.manual_used_amount) : '';
    tr.dataset.originalUsedAmount = String(usedVal);
    vals.forEach((v, i)=>{
      const td = document.createElement('td');
      td.textContent = v;
      // 사용금액(4번 칼럼)도 수동 보정이 필요할 수 있으므로 직접 수정 가능하게 한다. 잔액은 자동 계산 표시값이다.
      if(i <= 4) td.contentEditable = 'true';
      tr.appendChild(td);
    });
    tr.onclick = ()=>{
      qsa('#material-budget-table tbody tr').forEach(r=>r.classList.remove('selected'));
      tr.classList.add('selected');
    };
    tbody.appendChild(tr);
  }

  function updateMaterialRowRemaining(tr){
    if(!tr || !tr.children || tr.children.length < 6) return;
    const budget = num(tr.children[3]?.innerText || '0');
    const used = num(tr.children[4]?.innerText || '0');
    tr.children[5].textContent = money(budget - used);
  }

  function renderMaterialBudgetTable(){
    const tbody = qs('#material-budget-table tbody');
    if(!tbody) return;
    setMaterialProjectFilterOptions();
    const project = getMaterialProjectFilter();
    const rows = materialBudgetVisibleRows();
    tbody.innerHTML = '';
    rows.forEach(addMaterialRow);
    if(!tbody.children.length) addMaterialRow({project_code: project});
    const sumBudget = rows.reduce((s,r)=>s+num(r.budget_amount),0);
    const sumUsed = rows.reduce((s,r)=>s+num(r.used_amount),0);
    const sumRemain = sumBudget - sumUsed;
    const summary = qs('#material-summary');
    if(summary){
      const label = project ? `과제코드 ${project}` : '전체 과제코드';
      summary.innerHTML = `<span>${label}</span><span>배정액 ${money(sumBudget)}원</span><span>사용액 ${money(sumUsed)}원</span><span>잔액 ${money(sumRemain)}원</span>`;
    }
  }

  function readMaterialRowsFromTable(){
    return qsa('#material-budget-table tbody tr').map(tr=>{
      const row = {
        project_code: clean(tr.children[0]?.innerText).toUpperCase(),
        project_year: clean(tr.children[1]?.innerText),
        budget_type: clean(tr.children[2]?.innerText),
        budget_amount: num(tr.children[3]?.innerText)
      };
      // 사용금액 칼럼을 수정한 행만 수동 사용금액으로 저장한다.
      // 미수정 행은 기존처럼 DB의 상신완료 건 기준 자동 계산값을 유지한다.
      if(tr.dataset.usedEdited === '1'){
        row.used_amount = num(tr.children[4]?.innerText);
        row.manual_used_amount = row.used_amount;
      }else if(tr.dataset.manualUsedAmount !== undefined && tr.dataset.manualUsedAmount !== ''){
        row.manual_used_amount = num(tr.dataset.manualUsedAmount);
      }
      return row;
    }).filter(r=>r.project_code && r.project_year && r.budget_type);
  }

  async function saveMaterialBudget(){
    const editedRows = readMaterialRowsFromTable();
    const project = getMaterialProjectFilter();
    if(!editedRows.length){ alert('저장할 재료비관리 행이 없습니다.'); return; }
    const preservedRows = project
      ? (materialBudgetData.rows || []).filter(r=>clean(r.project_code).toUpperCase() !== project)
      : [];
    const rows = preservedRows.concat(editedRows);
    const res = await apiFetch('/api/purchase/material_budget/save', {method:'POST', body:JSON.stringify({rows})});
    materialBudgetData = res;
    materialBudgetCurrentProject = project || materialProjectFromForm() || (materialBudgetData.projects || [])[0] || '';
    renderMaterialBudgetTable();
    setOptions(qs('#pr-project-base'), materialBudgetData.projects || [], '과제코드');
    refreshDependentDropdowns();
    alert(res.message || '재료비관리 엑셀을 저장했습니다.');
  }

  async function openMaterialBudgetManager(){
    openModal('재료비관리', materialBudgetTableHtml());
    bindCopy('material-budget-table');
    await loadMaterialBudget();
    materialBudgetCurrentProject = materialProjectFromForm() || (materialBudgetData.projects || [])[0] || '';
    renderMaterialBudgetTable();
    const table = qs('#material-budget-table');
    if(table && table.dataset.materialEditableBound !== '1'){
      table.dataset.materialEditableBound = '1';
      table.addEventListener('input', e=>{
        const td = e.target && e.target.closest ? e.target.closest('td') : null;
        if(!td) return;
        const tr = td.closest('tr');
        if(!tr) return;
        if(td.cellIndex === 3 || td.cellIndex === 4) updateMaterialRowRemaining(tr);
        if(td.cellIndex === 4) tr.dataset.usedEdited = '1';
      }, true);
      table.addEventListener('blur', e=>{
        const td = e.target && e.target.closest ? e.target.closest('td') : null;
        if(!td) return;
        const tr = td.closest('tr');
        if(!tr) return;
        if(td.cellIndex === 3 || td.cellIndex === 4 || td.cellIndex === 5){
          td.textContent = money(td.innerText || '0');
          updateMaterialRowRemaining(tr);
        }
      }, true);
    }
    const filter = qs('#material-project-filter');
    if(filter) filter.onchange = ()=>{ materialBudgetCurrentProject = getMaterialProjectFilter(); renderMaterialBudgetTable(); };
    const addBtn = qs('#material-add-row');
    if(addBtn) addBtn.onclick = ()=>addMaterialRow({project_code:getMaterialProjectFilter()});
    const delBtn = qs('#material-del-row');
    if(delBtn) delBtn.onclick = ()=>{
      const tbody = qs('#material-budget-table tbody');
      if(!tbody) return;
      const selected = qsa('#material-budget-table tbody tr.selected');
      (selected.length ? selected : [tbody.lastElementChild]).forEach(tr=>tr && tr.remove());
      if(!tbody.children.length) addMaterialRow({});
    };
    const saveBtn = qs('#material-save');
    if(saveBtn) saveBtn.onclick = saveMaterialBudget;
    const refreshBtn = qs('#material-refresh');
    if(refreshBtn) refreshBtn.onclick = async()=>{ await loadMaterialBudget(); setMaterialProjectFilterOptions(); renderMaterialBudgetTable(); };
  }

  function bindMaterialBudgetUI(){
    const manageBtn = qs('#material-manage');
    if(manageBtn && manageBtn.dataset.bound !== '1'){
      manageBtn.dataset.bound = '1';
      manageBtn.onclick = openMaterialBudgetManager;
    }
    const base = qs('#pr-project-base');
    if(base && base.dataset.bound !== '1'){
      base.dataset.bound = '1';
      base.addEventListener('change', refreshDependentDropdowns);
    }
    const year = qs('#pr-project-year');
    if(year && year.dataset.bound !== '1'){
      year.dataset.bound = '1';
      year.addEventListener('change', refreshTypeDropdown);
    }
    const type = qs('#pr-item-type');
    if(type && type.dataset.bound !== '1'){
      type.dataset.bound = '1';
      type.addEventListener('change', ()=>{ renderBudgetStatus(); if(typeof updateTitlePreview === 'function') updateTitlePreview(); });
    }
    const items = qs('#pr-items');
    if(items && items.dataset.materialBudgetBound !== '1'){
      items.dataset.materialBudgetBound = '1';
      items.addEventListener('input', renderBudgetStatus, true);
      items.addEventListener('keyup', renderBudgetStatus, true);
    }
  }

  // 기존 updateTitlePreview는 #pr-project-code/#pr-category/#pr-sub-category/#pr-item-type 값을 그대로 읽으므로,
  // 드롭다운 변경 시 생성된 RxxGAxx_0x 코드만 동기화하면 기존 제목 생성 로직을 유지할 수 있다.
  if(typeof updateTitlePreview === 'function' && !updateTitlePreview.__materialBudgetWrap){
    const oldUpdateTitlePreview = updateTitlePreview;
    updateTitlePreview = function(){
      composeProjectCode();
      const r = oldUpdateTitlePreview.apply(this, arguments);
      renderBudgetStatus();
      return r;
    };
    updateTitlePreview.__materialBudgetWrap = true;
  }

  // createPurchase payload에 연차/재료비 구분을 안정적으로 추가하기 위해 fetch 직전 DOM 값을 동기화한다.
  if(typeof createPurchase === 'function' && !createPurchase.__materialBudgetWrap){
    const oldCreatePurchase = createPurchase;
    createPurchase = async function(markComplete){
      composeProjectCode();
      renderBudgetStatus();
      return await oldCreatePurchase.apply(this, arguments);
    };
    createPurchase.__materialBudgetWrap = true;
  }

  document.addEventListener('DOMContentLoaded', ()=>{
    bindMaterialBudgetUI();
    loadMaterialBudget();
  });
  setInterval(()=>{ bindMaterialBudgetUI(); renderBudgetStatus(); }, 1000);

  window.loadMaterialBudget = loadMaterialBudget;
  window.openMaterialBudgetManager = openMaterialBudgetManager;
  window.deverpMaterialBudgetSelected = function(){ return findSelectedBudgetRow(); };
})();


/* ─────────────────────────────────────────────
   EDITABLE_TABLE_EXCEL_LIKE_PATCH_20260520
   수정 가능한 표 셀 1회 클릭 편집 + Excel식 붙여넣기/키 이동
   ───────────────────────────────────────────── */
(function(){
  if(window.__DEVERP_EDITABLE_TABLE_EXCEL_LIKE_PATCH_20260520__) return;
  window.__DEVERP_EDITABLE_TABLE_EXCEL_LIKE_PATCH_20260520__ = true;

  const cleanText = v => String(v ?? '').split('\r').join('');

  function editableCellFromEvent(e){
    const td = e.target && e.target.closest ? e.target.closest('td') : null;
    if(!td || !td.isContentEditable) return null;
    const table = td.closest('table.grid.editable');
    if(!table) return null;
    return td;
  }

  function editableColumnsFor(table, tr){
    const ref = tr || table?.tBodies?.[0]?.rows?.[0];
    if(!ref) return [];
    return Array.from(ref.cells).map((td, i)=>td.isContentEditable ? i : -1).filter(i=>i >= 0);
  }

  function selectRowForEditableCell(td){
    const tr = td.closest('tr');
    const tbody = tr?.parentElement;
    if(!tr || !tbody) return;
    Array.from(tbody.children).forEach(r=>r.classList.remove('selected'));
    tr.classList.add('selected');
  }

  function ensureTableRow(table, rowIndex){
    const tbody = table?.tBodies?.[0];
    if(!tbody) return null;
    while(tbody.rows.length <= rowIndex){
      if((table.id === 'pr-items' || table.id === 'actual-items') && typeof addItemRow === 'function'){
        addItemRow(table.id, {});
      }else if(table.id === 'vendors-table' && typeof addVendorRow === 'function'){
        addVendorRow({});
      }else{
        const template = tbody.rows[tbody.rows.length - 1];
        const cols = table.tHead?.rows?.[0]?.cells?.length || template?.cells?.length || 1;
        const tr = document.createElement('tr');
        for(let c=0; c<cols; c++){
          const td = document.createElement('td');
          const editable = template?.cells?.[c]?.isContentEditable || (table.id === 'material-budget-table' && c <= 4) || (table.id === 'pr-vendors' && c > 0);
          if(editable) td.contentEditable = 'true';
          td.textContent = (!editable && c === 0) ? String(tbody.rows.length + 1) : '';
          tr.appendChild(td);
        }
        tr.onclick = ()=>selectRow(table.id, tr);
        tbody.appendChild(tr);
      }
    }
    return tbody.rows[rowIndex];
  }

  function renumberTable(table){
    if(!table?.tBodies?.[0]) return;
    if(['pr-items','actual-items','pr-vendors'].includes(table.id)){
      Array.from(table.tBodies[0].rows).forEach((tr, i)=>{ if(tr.cells[0] && !tr.cells[0].isContentEditable) tr.cells[0].textContent = i + 1; });
    }
  }

  function recalcRow(table, tr){
    try{
      if((table.id === 'pr-items' || table.id === 'actual-items') && typeof calcItemAmount === 'function') calcItemAmount(tr);
      if(table.id === 'pr-items' && typeof renderBudgetStatus === 'function') renderBudgetStatus();
    }catch(e){}
  }

  function moveToEditable(table, tr, colIndex, rowDelta, colDelta){
    const tbody = table?.tBodies?.[0];
    if(!tbody || !tr) return;
    const editableCols = editableColumnsFor(table, tr);
    if(!editableCols.length) return;
    let rowIndex = Array.from(tbody.rows).indexOf(tr) + rowDelta;
    let targetCol = colIndex;

    if(colDelta){
      const pos = editableCols.indexOf(colIndex);
      let nextPos = pos >= 0 ? pos + colDelta : 0;
      if(nextPos >= editableCols.length){ nextPos = 0; rowIndex += 1; }
      if(nextPos < 0){ nextPos = editableCols.length - 1; rowIndex -= 1; }
      targetCol = editableCols[nextPos];
    }

    if(rowIndex < 0) rowIndex = 0;
    const nextTr = ensureTableRow(table, rowIndex);
    const td = nextTr?.cells?.[targetCol];
    if(td && td.isContentEditable){
      deverpFocusEditableCell(td);
      selectRowForEditableCell(td);
    }
  }

  document.addEventListener('click', e=>{
    const td = editableCellFromEvent(e);
    if(!td) return;
    setTimeout(()=>{
      deverpFocusEditableCell(td, e);
      selectRowForEditableCell(td);
    }, 0);
  }, true);

  document.addEventListener('keydown', e=>{
    const td = editableCellFromEvent(e);
    if(!td) return;
    const table = td.closest('table.grid.editable');
    const tr = td.closest('tr');
    if(e.key === 'Enter'){
      e.preventDefault();
      moveToEditable(table, tr, td.cellIndex, e.shiftKey ? -1 : 1, 0);
    }else if(e.key === 'Tab'){
      e.preventDefault();
      moveToEditable(table, tr, td.cellIndex, 0, e.shiftKey ? -1 : 1);
    }
  }, true);

  document.addEventListener('paste', e=>{
    const td = editableCellFromEvent(e);
    if(!td) return;
    const text = e.clipboardData?.getData('text/plain') || '';
    if(!text.includes('\t') && !text.includes('\n')) return;
    e.preventDefault();

    const table = td.closest('table.grid.editable');
    const tbody = table?.tBodies?.[0];
    const startTr = td.closest('tr');
    if(!table || !tbody || !startTr) return;

    const startRow = Array.from(tbody.rows).indexOf(startTr);
    const startCol = td.cellIndex;
    const rows = cleanText(text).replace(/\n$/, '').split('\n').map(r=>r.split('\t'));

    rows.forEach((cols, rOffset)=>{
      const tr = ensureTableRow(table, startRow + rOffset);
      if(!tr) return;
      let writeCol = startCol;
      cols.forEach(value=>{
        while(tr.cells[writeCol] && !tr.cells[writeCol].isContentEditable) writeCol += 1;
        const cell = tr.cells[writeCol];
        if(cell && cell.isContentEditable){
          cell.textContent = value;
          cell.dispatchEvent(new Event('input', {bubbles:true}));
        }
        writeCol += 1;
      });
      recalcRow(table, tr);
    });
    renumberTable(table);
    try{ if(typeof updateTitlePreview === 'function') updateTitlePreview(); }catch(e){}
  }, true);
})();




/* DevERP QUALITY CONTROL BUTTON HOTFIX - force visible, no overwrite */
(function(){
  if (window.__DEV_ERP_QC_BUTTON_HOTFIX__) return;
  window.__DEV_ERP_QC_BUTTON_HOTFIX__ = true;

  function q(sel, root){ return (root || document).querySelector(sel); }
  function qa(sel, root){ return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function getSelectedReceiptItemIds(){
    try{
      if (typeof selectedReceiptIds !== 'undefined' && selectedReceiptIds && selectedReceiptIds.size) {
        return Array.from(selectedReceiptIds).map(Number).filter(Boolean);
      }
    } catch(e) {}
    return qa('#receipt-table input[type="checkbox"]:checked, #receipt-tbody input[type="checkbox"]:checked, #page-receipt table input[type="checkbox"]:checked')
      .map(function(cb){ return Number(cb.dataset.id || cb.value || cb.getAttribute('data-item-id') || cb.getAttribute('data-id') || 0); })
      .filter(Boolean);
  }

  async function exportQualityControl(){
    var ids = getSelectedReceiptItemIds();
    if (!ids.length) {
      alert('품질관리 파일로 내보낼 품목을 선택하세요. 문서번호 왼쪽 + 펼침 후 품목 체크 또는 문서번호 체크로 선택할 수 있습니다.');
      return;
    }
    var btn = q('#quality-control-btn');
    var oldTxt = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '품질관리 파일 생성 중...'; }
    try{
      var token = localStorage.getItem('deverp_token') || '';
      var headers = {'Content-Type':'application/json'};
      if (token) headers.Authorization = 'Bearer ' + token;
      var res = await fetch('/api/inventory/quality_control_export', {
        method:'POST',
        headers: headers,
        body: JSON.stringify({item_ids: ids})
      });
      if (!res.ok) {
        var parsed = await deverpReadResponseJsonOrText(res);
        throw new Error(deverpResponseMessage(parsed, 'HTTP ' + res.status));
      }
      var blob = await res.blob();
      var name = '품질관리_진행LIST.xlsx';
      var cd = res.headers.get('content-disposition') || '';
      var m = cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
      if (m) {
        try { name = decodeURIComponent(m[1] || m[2]); } catch(e) { name = m[1] || m[2] || name; }
      }
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(function(){ try{ URL.revokeObjectURL(a.href); }catch(e){} a.remove(); }, 3000);
    } catch(e) {
      alert('품질관리 파일 생성 실패: ' + (e && e.message ? e.message : e));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = oldTxt || '📊 품질관리'; }
    }
  }

  function forceQualityButton(){
    var receiptPage = q('#page-receipt') || qa('section.page').find(function(sec){ return (sec.textContent || '').indexOf('입고 관리') >= 0; });
    if (!receiptPage) return;
    var legend = q('.legend', receiptPage);
    var actions = q('.title-row .actions', receiptPage) || q('.actions', receiptPage);
    var btn = q('#quality-control-btn');
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'quality-control-btn';
      btn.type = 'button';
      btn.textContent = '📊 품질관리';
    }
    btn.className = 'btn purple quality-control-inline';
    btn.style.display = 'inline-flex';
    btn.style.alignItems = 'center';
    btn.style.justifyContent = 'center';
    btn.style.visibility = 'visible';
    btn.hidden = false;
    btn.disabled = false;
    btn.onclick = exportQualityControl;
    if (legend && btn.parentElement !== legend) {
      legend.appendChild(btn);
    } else if (!legend && actions && btn.parentElement !== actions) {
      var ref = q('#in-btn', actions) || q('#out-btn', actions) || q('#receipt-delete-btn', actions) || null;
      if (ref) actions.insertBefore(btn, ref);
      else actions.appendChild(btn);
    }
  }

  function start(){
    forceQualityButton();
    setInterval(forceQualityButton, 1000);
    try { new MutationObserver(forceQualityButton).observe(document.body, {childList:true, subtree:true}); } catch(e) {}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
/* END DevERP QUALITY CONTROL BUTTON HOTFIX */



/* ─────────────────────────────────────────────
   DEV_ERP v2.1.7: 업체별 합계 행 업체명 편집 + 실제입고품 업체별 관리
   ───────────────────────────────────────────── */
(function(){
  function qsaLocal(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }
  function textClean(v){ return String(v ?? '').replace(/\s+/g, ' ').trim(); }
  function isItemTable(tableId){ return tableId === 'pr-items' || tableId === 'actual-items'; }
  function subtotalNameFromText(text){
    const raw = textClean(text);
    const m = raw.match(/\((.*)\)/);
    if(m && textClean(m[1])) return textClean(m[1]);
    return textClean(raw.replace(/^합계금액\s*/,'').replace(/^[:：\-–—]/,'')) || '업체 미지정';
  }
  function tableItemRows(tableId){
    return qsaLocal('#'+tableId+' tbody tr').filter(tr=>!(tr.classList && tr.classList.contains('vendor-total-row')));
  }
  function nonBlankItemRows(tableId){
    return tableItemRows(tableId).filter(tr=>{
      try{
        if(typeof isBlankItemRow === 'function' && isBlankItemRow(tr)) return false;
      }catch(e){}
      return [1,2,3,4,8].some(i=>textClean(tr.children[i]?.innerText));
    });
  }
  function rowVendorName(tr){
    return textClean(tr.dataset.vendorName || tr.dataset.vendor || tr.children?.[8]?.innerText || '') || '업체 미지정';
  }
  function rowVendorIndex(tr){ return tr.dataset.vendorIndex ?? ''; }
  function updatePrVendorTableName(vendorIndex, oldName, newName){
    qsaLocal('#pr-vendors tbody tr').forEach((tr, idx)=>{
      const c = tr.children;
      const curName = textClean(c?.[1]?.innerText || '');
      const vi = tr.dataset.vendorIndex ?? String(idx);
      const matchByIndex = vendorIndex !== '' && String(vi) === String(vendorIndex);
      const matchByName = oldName && curName === oldName;
      if(matchByIndex || matchByName){
        if(c && c[1]) c[1].innerText = newName;
        tr.dataset.vendorIndex = vendorIndex !== '' ? vendorIndex : vi;
      }
    });
  }
  function updateParsedVendorName(vendorIndex, oldName, newName){
    try{
      if(typeof parsedVendors === 'undefined' || !Array.isArray(parsedVendors)) return;
      parsedVendors = parsedVendors.map((v, idx)=>{
        const vi = v.vendor_index ?? idx;
        const cur = textClean(v.name || v.vendor_name || v.vendor || '');
        const matchByIndex = vendorIndex !== '' && String(vi) === String(vendorIndex);
        const matchByName = oldName && cur === oldName;
        if(matchByIndex || matchByName){
          return Object.assign({}, v, {name:newName, vendor_name:newName, vendor:newName});
        }
        return v;
      });
    }catch(e){}
  }
  window.deverpApplyVendorSubtotalName = function(tableId, vendorIndex, oldName, newName){
    tableId = tableId || 'pr-items';
    newName = textClean(newName) || '업체 미지정';
    oldName = textClean(oldName);
    const rows = tableItemRows(tableId);
    rows.forEach(tr=>{
      const vi = rowVendorIndex(tr);
      const cur = textClean(tr.dataset.vendorName || '');
      const matchByIndex = vendorIndex !== '' && String(vi) === String(vendorIndex);
      const matchByName = oldName && (cur === oldName || rowVendorName(tr) === oldName);
      if(matchByIndex || matchByName){
        tr.dataset.vendorName = newName;
        if(vendorIndex !== '') tr.dataset.vendorIndex = vendorIndex;
      }
    });
    if(tableId === 'pr-items'){
      updateParsedVendorName(vendorIndex, oldName, newName);
      updatePrVendorTableName(vendorIndex, oldName, newName);
    }
    try{ deverpRenderVendorSubtotalRows(tableId); }catch(e){}
  };

  // 기존 합계행 렌더러를 업체명 편집 가능 버전으로 교체한다.
  window.deverpRenderVendorSubtotalRows = deverpRenderVendorSubtotalRows = function(tableId='pr-items'){
    const tbody = document.querySelector('#'+tableId+' tbody');
    if(!tbody) return;
    if(typeof deverpRemoveVendorTotalRows === 'function') deverpRemoveVendorTotalRows(tableId);
    if(!isItemTable(tableId)) return;
    const rows = nonBlankItemRows(tableId);
    if(!rows.length){
      if(typeof deverpRenumberItemRows === 'function') deverpRenumberItemRows(tableId);
      return;
    }
    const groups = [];
    let current = null;
    rows.forEach(tr=>{
      const name = rowVendorName(tr);
      const vendorIndex = rowVendorIndex(tr);
      const key = String(vendorIndex) + '|' + name;
      if(!current || current.key !== key){
        current = {key, name, vendorIndex, rows:[], total:0};
        groups.push(current);
      }
      current.rows.push(tr);
      current.total += parseFloat((tr.children[6]?.innerText||'0').replace(/,/g,'')) || 0;
    });
    groups.forEach(g=>{
      const last = g.rows[g.rows.length - 1];
      if(!last) return;
      const tr = document.createElement('tr');
      tr.className = 'vendor-total-row';
      tr.dataset.vendorTotal = '1';
      tr.dataset.vendorName = g.name;
      tr.dataset.vendorIndex = g.vendorIndex ?? '';

      const td0 = document.createElement('td');
      td0.textContent = '';
      tr.appendChild(td0);

      const tdName = document.createElement('td');
      tdName.colSpan = 5;
      tdName.contentEditable = 'true';
      tdName.dataset.vendorSubtotalName = '1';
      tdName.dataset.vendorName = g.name;
      tdName.dataset.vendorIndex = g.vendorIndex ?? '';
      tdName.title = '업체명을 수정하면 해당 업체 품목/입고 관리/결재상신 메시지에 반영됩니다.';
      tdName.textContent = `합계금액(${g.name || '업체 미지정'})`;
      tdName.addEventListener('keydown', ev=>{
        if(ev.key === 'Enter'){
          ev.preventDefault();
          tdName.blur();
        }
      });
      tdName.addEventListener('blur', ()=>{
        const newName = subtotalNameFromText(tdName.innerText);
        window.deverpApplyVendorSubtotalName(tableId, g.vendorIndex ?? '', g.name || '', newName);
      });
      tr.appendChild(tdName);

      const tdAmt = document.createElement('td');
      tdAmt.textContent = (typeof deverpFormatWon === 'function') ? deverpFormatWon(g.total) : String(Math.round(g.total||0));
      tr.appendChild(tdAmt);
      const tdAxis = document.createElement('td');
      tdAxis.textContent = '';
      tr.appendChild(tdAxis);
      const tdCount = document.createElement('td');
      tdCount.textContent = `${g.rows.length}개 품목`;
      tr.appendChild(tdCount);
      last.insertAdjacentElement('afterend', tr);
    });
    if(typeof deverpRenumberItemRows === 'function') deverpRenumberItemRows(tableId);
  };

  function copyPrItemsToActualIfBlank(){
    const actualBody = document.querySelector('#actual-items tbody');
    const prBody = document.querySelector('#pr-items tbody');
    if(!actualBody || !prBody || typeof addItemRow !== 'function') return;
    const actualRows = nonBlankItemRows('actual-items');
    if(actualRows.length) return;
    const srcRows = nonBlankItemRows('pr-items');
    if(!srcRows.length) return;
    actualBody.innerHTML = '';
    srcRows.forEach(tr=>{
      addItemRow('actual-items', {
        item_name: textClean(tr.children[1]?.innerText),
        spec: textClean(tr.children[2]?.innerText),
        unit_price: parseFloat((tr.children[3]?.innerText || '0').replace(/,/g,'')) || 0,
        quantity: parseFloat((tr.children[4]?.innerText || '0').replace(/,/g,'')) || 0,
        unit: textClean(tr.children[5]?.innerText) || 'EA',
        amount: parseFloat((tr.children[6]?.innerText || '0').replace(/,/g,'')) || 0,
        axis: textClean(tr.children[7]?.innerText),
        maker: textClean(tr.children[8]?.innerText),
        note: textClean(tr.children[8]?.innerText),
        vendor_name: textClean(tr.dataset.vendorName || ''),
        vendor_index: tr.dataset.vendorIndex ?? ''
      });
    });
    deverpRenderVendorSubtotalRows('actual-items');
  }

  const oldAddItemRow = addItemRow;
  addItemRow = function(tableId, item={}){
    if(isItemTable(tableId) && typeof deverpRemoveVendorTotalRows === 'function') deverpRemoveVendorTotalRows(tableId);
    const r = oldAddItemRow.apply(this, arguments);
    if(isItemTable(tableId)){
      setTimeout(()=>deverpRenderVendorSubtotalRows(tableId), 0);
    }
    return r;
  };

  const oldDelSelectedRow = delSelectedRow;
  delSelectedRow = function(tableId){
    const r = oldDelSelectedRow.apply(this, arguments);
    if(isItemTable(tableId)) setTimeout(()=>deverpRenderVendorSubtotalRows(tableId), 0);
    return r;
  };

  const oldCalcItemAmount = calcItemAmount;
  calcItemAmount = function(tr){
    const r = oldCalcItemAmount.apply(this, arguments);
    const table = tr && tr.closest ? tr.closest('table') : null;
    if(table && isItemTable(table.id)) setTimeout(()=>deverpRenderVendorSubtotalRows(table.id), 0);
    return r;
  };

  // 실제 입고품 다름을 체크하면 현재 구매의뢰 품목표를 업체 정보까지 복사해 동일한 업체별 표로 시작한다.
  document.addEventListener('change', ev=>{
    if(ev.target && ev.target.id === 'actual-diff' && ev.target.checked){
      setTimeout(copyPrItemsToActualIfBlank, 0);
    }
  });

  document.addEventListener('input', ev=>{
    const tr = ev.target && ev.target.closest ? ev.target.closest('tr') : null;
    const table = ev.target && ev.target.closest ? ev.target.closest('table') : null;
    if(tr && table && isItemTable(table.id) && !(tr.classList && tr.classList.contains('vendor-total-row'))){
      setTimeout(()=>deverpRenderVendorSubtotalRows(table.id), 0);
    }
  });

  document.addEventListener('DOMContentLoaded', ()=>{
    setTimeout(()=>{
      try{ deverpRenderVendorSubtotalRows('pr-items'); }catch(e){}
      try{ deverpRenderVendorSubtotalRows('actual-items'); }catch(e){}
    }, 500);
  });
})();

/* DEV_ERP v2.1.7: 결재상신 메시지 실제입고품 업체별 합계 표 */
(function(){
  function clean(v){ return String(v ?? '').replace(/\s+/g, ' ').trim(); }
  function amountOf(it){
    const amount = parseFloat(String(it.amount||'0').replace(/,/g,'')) || 0;
    if(amount) return Math.round(amount);
    const p = parseFloat(String(it.unit_price||'0').replace(/,/g,'')) || 0;
    const q = parseFloat(String(it.quantity||'0').replace(/,/g,'')) || 0;
    return Math.round(p*q);
  }
  function vendorNameOf(it, idx){
    if(it.vendor_name) return clean(it.vendor_name);
    if(it.vendor) return clean(it.vendor);
    if(it.maker) return clean(it.maker);
    if(it.note) return clean(it.note);
    return '업체 미지정';
  }
  function groupedItemTable(items){
    const rows = (items || []).filter(it=>clean(it.item_name || it.spec));
    if(!rows.length) return '';
    const out = [];
    out.push(['No','업체명','품명','규격','예상단가','수량','단위','예상금액','축 구분','비고(제조사)'].join('\t'));
    let curName = null, curTotal = 0, curCount = 0, no = 1;
    const flush = ()=>{
      if(curName === null) return;
      out.push(['', `합계금액(${curName})`, '', '', '', '', '', (typeof deverpFormatWon === 'function' ? deverpFormatWon(curTotal) : String(curTotal))+'원', '', `${curCount}개 품목`].join('\t'));
    };
    rows.forEach((it, idx)=>{
      const vn = vendorNameOf(it, idx);
      if(curName !== null && vn !== curName){ flush(); curTotal = 0; curCount = 0; }
      if(curName === null || vn !== curName) curName = vn;
      const amt = amountOf(it);
      curTotal += amt; curCount += 1;
      out.push([
        String(no++),
        vn,
        clean(it.item_name),
        clean(it.spec),
        clean(it.unit_price),
        clean(it.quantity),
        clean(it.unit || 'EA'),
        (typeof deverpFormatWon === 'function' ? deverpFormatWon(amt) : String(amt)),
        clean(it.axis),
        clean(it.maker || it.note)
      ].join('\t'));
    });
    flush();
    return out.join('\n');
  }
  deverpApprovalActualItemsTable = function(items){ return groupedItemTable(items); };
  const oldProjectMsg = (typeof deverpApprovalProjectDiffMessage === 'function') ? deverpApprovalProjectDiffMessage : ()=>'';
  deverpBuildApprovalCopyMessage = function(payload){
    const sections = [];
    const projectMsg = oldProjectMsg(payload);
    if(projectMsg) sections.push(projectMsg);
    // 업체별 견적 합계는 항상 1번 표(견적 자동인식 후 사용자가 수정한 최종 품목표) 기준입니다.
    // 실제 입고품 다름 체크 시에도 실제 입고품 표는 별도 안내 표로만 표시합니다.
    const vendorTotals = (typeof deverpApprovalVendorTotalsTable === 'function') ? deverpApprovalVendorTotalsTable(payload.items || []) : '';
    if(vendorTotals){
      const no = sections.length + 1;
      sections.push(`${no}. 업체별 합계입니다.\n${vendorTotals}`);
    }
    if(payload.actual_received_diff){
      const table = groupedItemTable(payload.actual_items || []);
      if(table){
        const no = sections.length + 1;
        sections.push(`${no}. 실제 입고품 리스트니 참고부탁드립니다.\n${table}`);
      }
    }
    const no = sections.length + 1;
    sections.push(`${no}. DEV_ERP로 작성된 구매의뢰서입니다\n   (접속주소: 192.168.100.180:8000)`);
    return sections.join('\n\n');
  };
})();


/* DEV_ERP v2.2.5 actual/quote vendor split patch */
console.info('DevERP WEB v2.2.5 loaded');

/* DEV_ERP v2.2.5: 실제입고품 다름 시 비용처리 업체와 입고관리 업체 분리 */
(function(){
  function qsaLocal(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }
  function clean(v){ return String(v ?? '').replace(/\s+/g, ' ').trim(); }
  function isVendorTotalRow(tr){ return !!(tr && tr.classList && tr.classList.contains('vendor-total-row')); }
  function isItemTableId(tableId){ return tableId === 'pr-items' || tableId === 'actual-items'; }
  function itemRows(tableId){ return qsaLocal('#'+tableId+' tbody tr').filter(tr=>!isVendorTotalRow(tr)); }
  function parseNum(v){ return parseFloat(String(v ?? '0').replace(/,/g,'')) || 0; }
  function fmt(v){ return (Math.round(Number(v)||0)).toLocaleString(); }
  function vendorCellIndex(tableId){ return tableId === 'actual-items' ? 9 : -1; }
  function ensureActualVendorCell(tr){
    const table = tr && tr.closest ? tr.closest('table') : null;
    if(!tr || !table || table.id !== 'actual-items' || isVendorTotalRow(tr)) return;
    while(tr.children.length < 10){
      const td = document.createElement('td');
      td.contentEditable = 'true';
      tr.appendChild(td);
    }
    const vtd = tr.children[9];
    if(!vtd.dataset.actualVendorCell){
      vtd.dataset.actualVendorCell = '1';
      vtd.title = '실제 입고 업체명입니다. 이 값 기준으로 QR·입고 관리가 업체별로 생성됩니다.';
      vtd.addEventListener('input', ()=>{
        tr.dataset.vendorName = clean(vtd.innerText);
        setTimeout(()=>deverpRenderVendorSubtotalRows('actual-items'), 0);
      });
      vtd.addEventListener('blur', ()=>{
        tr.dataset.vendorName = clean(vtd.innerText);
        deverpRenderVendorSubtotalRows('actual-items');
      });
    }
  }
  function rowVendorName221(tr, tableId){
    const idx = vendorCellIndex(tableId);
    if(idx >= 0){
      const fromCell = clean(tr.children?.[idx]?.innerText || '');
      if(fromCell) return fromCell;
    }
    const fromData = clean(tr.dataset.vendorName || tr.dataset.vendor || '');
    if(fromData) return fromData;
    if(tableId !== 'actual-items'){
      const maker = clean(tr.children?.[8]?.innerText || '');
      if(maker) return maker;
    }
    return '업체 미지정';
  }
  function vendorIndexOf(tr){ return tr.dataset.vendorIndex ?? ''; }
  function isBlankRow221(tr){
    if(!tr || isVendorTotalRow(tr)) return true;
    return ![1,2,3,4,8].some(i=>clean(tr.children?.[i]?.innerText));
  }
  function renumber221(tableId){
    let n=1;
    itemRows(tableId).forEach(tr=>{ if(tr.children[0]) tr.children[0].textContent = n++; });
  }
  function removeTotals221(tableId){ qsaLocal('#'+tableId+' tbody tr.vendor-total-row').forEach(tr=>tr.remove()); }
  function amountOfRow(tr){
    const amount = parseNum(tr.children?.[6]?.innerText);
    if(amount) return Math.round(amount);
    return Math.round(parseNum(tr.children?.[3]?.innerText) * parseNum(tr.children?.[4]?.innerText));
  }

  const previousAddItemRow = typeof addItemRow === 'function' ? addItemRow : null;
  addItemRow = function(tableId, item={}){
    if(!isItemTableId(tableId)) return previousAddItemRow ? previousAddItemRow.apply(this, arguments) : undefined;
    const tbody = document.querySelector('#'+tableId+' tbody');
    if(!tbody) return;
    removeTotals221(tableId);
    const tr = document.createElement('tr');
    const vendorName = clean(item.vendor_name || item.vendor || '');
    tr.dataset.vendorName = vendorName;
    tr.dataset.vendorIndex = item.vendor_index ?? '';
    const idx = itemRows(tableId).length + 1;
    const amount = item.amount || ((Number(item.unit_price||0) * Number(item.quantity||0)) || '');
    const vals = [idx, item.item_name||'', item.spec||'', item.unit_price||'', item.quantity||'', item.unit||'EA', amount, item.axis||'', item.maker||item.note||''];
    vals.forEach((v,i)=>{
      const td=document.createElement('td');
      td.textContent = v;
      if(i>0){
        td.contentEditable='true';
        if(i===3 || i===4){
          td.addEventListener('input',()=>{ calcItemAmount(tr); setTimeout(()=>deverpRenderVendorSubtotalRows(tableId),0); });
        }
      }
      tr.appendChild(td);
    });
    if(tableId === 'actual-items'){
      const td=document.createElement('td');
      td.textContent = vendorName;
      td.contentEditable='true';
      tr.appendChild(td);
      ensureActualVendorCell(tr);
    }
    tr.onclick=()=>selectRow(tableId,tr);
    tbody.appendChild(tr);
    calcItemAmount(tr);
    setTimeout(()=>deverpRenderVendorSubtotalRows(tableId), 0);
    return tr;
  };

  const previousGetItems = typeof getItems === 'function' ? getItems : null;
  getItems = function(tableId){
    if(!isItemTableId(tableId)) return previousGetItems ? previousGetItems.apply(this, arguments) : [];
    if(tableId === 'actual-items') itemRows('actual-items').forEach(ensureActualVendorCell);
    return itemRows(tableId).map(tr=>{
      const vendorName = rowVendorName221(tr, tableId);
      if(tableId === 'actual-items') tr.dataset.vendorName = vendorName === '업체 미지정' ? '' : vendorName;
      return {
        item_name: clean(tr.children?.[1]?.innerText),
        spec: clean(tr.children?.[2]?.innerText),
        unit_price: parseNum(tr.children?.[3]?.innerText),
        quantity: parseNum(tr.children?.[4]?.innerText),
        unit: clean(tr.children?.[5]?.innerText) || 'EA',
        amount: parseNum(tr.children?.[6]?.innerText),
        axis: clean(tr.children?.[7]?.innerText),
        maker: clean(tr.children?.[8]?.innerText),
        vendor_name: tableId === 'actual-items' ? (vendorName === '업체 미지정' ? '' : vendorName) : (clean(tr.dataset.vendorName || '') || clean(tr.children?.[8]?.innerText)),
        note: clean(tr.children?.[8]?.innerText),
        vendor_index: tr.dataset.vendorIndex === '' ? null : Number(tr.dataset.vendorIndex)
      };
    }).filter(x=>x.item_name || x.spec);
  };

  const previousBlank = typeof isBlankItemRow === 'function' ? isBlankItemRow : null;
  isBlankItemRow = function(tr){
    const table = tr && tr.closest ? tr.closest('table') : null;
    if(table && isItemTableId(table.id)) return isBlankRow221(tr);
    return previousBlank ? previousBlank.apply(this, arguments) : isBlankRow221(tr);
  };

  const previousDel = typeof delSelectedRow === 'function' ? delSelectedRow : null;
  delSelectedRow = function(tableId){
    if(!isItemTableId(tableId)) return previousDel ? previousDel.apply(this, arguments) : undefined;
    const tbody=document.querySelector('#'+tableId+' tbody'); if(!tbody) return;
    removeTotals221(tableId);
    const sel=qsaLocal('#'+tableId+' tbody tr.selected').filter(tr=>!isVendorTotalRow(tr));
    const fallback = Array.from(tbody.children).reverse().find(tr=>!isVendorTotalRow(tr));
    (sel.length?sel:[fallback]).forEach(tr=>tr&&tr.remove());
    renumber221(tableId);
    if(!itemRows(tableId).length) addItemRow(tableId);
    deverpRenderVendorSubtotalRows(tableId);
  };

  window.deverpApplyVendorSubtotalName = function(tableId, vendorIndex, oldName, newName){
    tableId = tableId || 'pr-items';
    newName = clean(newName) || '업체 미지정';
    oldName = clean(oldName);
    itemRows(tableId).forEach(tr=>{
      const cur = rowVendorName221(tr, tableId);
      const vi = vendorIndexOf(tr);
      const matchByIndex = vendorIndex !== '' && String(vi) === String(vendorIndex);
      const matchByName = oldName && cur === oldName;
      if(matchByIndex || matchByName){
        tr.dataset.vendorName = newName;
        if(vendorIndex !== '') tr.dataset.vendorIndex = vendorIndex;
        if(tableId === 'actual-items'){
          ensureActualVendorCell(tr);
          if(tr.children[9]) tr.children[9].innerText = newName;
        }
      }
    });
    if(tableId === 'pr-items'){
      try{
        if(Array.isArray(parsedVendors)){
          parsedVendors = parsedVendors.map((v, idx)=>{
            const vi = v.vendor_index ?? idx;
            const cur = clean(v.name || v.vendor_name || v.vendor || '');
            const matchByIndex = vendorIndex !== '' && String(vi) === String(vendorIndex);
            const matchByName = oldName && cur === oldName;
            return (matchByIndex || matchByName) ? Object.assign({}, v, {name:newName, vendor_name:newName, vendor:newName}) : v;
          });
        }
      }catch(e){}
      qsaLocal('#pr-vendors tbody tr').forEach((tr, idx)=>{
        const vi = tr.dataset.vendorIndex ?? String(idx);
        const cur = clean(tr.children?.[1]?.innerText || '');
        const matchByIndex = vendorIndex !== '' && String(vi) === String(vendorIndex);
        const matchByName = oldName && cur === oldName;
        if(matchByIndex || matchByName){ if(tr.children[1]) tr.children[1].innerText = newName; tr.dataset.vendorIndex = vi; }
      });
    }
    deverpRenderVendorSubtotalRows(tableId);
  };

  window.deverpRenderVendorSubtotalRows = deverpRenderVendorSubtotalRows = function(tableId='pr-items'){
    const tbody=document.querySelector('#'+tableId+' tbody'); if(!tbody) return;
    removeTotals221(tableId);
    if(!isItemTableId(tableId)) return;
    if(tableId === 'actual-items') itemRows(tableId).forEach(ensureActualVendorCell);
    const rows=itemRows(tableId).filter(tr=>!isBlankRow221(tr));
    if(!rows.length){ renumber221(tableId); return; }
    const groups=[];
    let current=null;
    rows.forEach(tr=>{
      const name=rowVendorName221(tr, tableId);
      if(tableId === 'actual-items') tr.dataset.vendorName = name === '업체 미지정' ? '' : name;
      const vendorIndex=vendorIndexOf(tr);
      const key=String(vendorIndex)+'|'+name;
      if(!current || current.key!==key){ current={key,name,vendorIndex,rows:[],total:0}; groups.push(current); }
      current.rows.push(tr); current.total += amountOfRow(tr);
    });
    groups.forEach(g=>{
      const last=g.rows[g.rows.length-1]; if(!last) return;
      const tr=document.createElement('tr'); tr.className='vendor-total-row'; tr.dataset.vendorTotal='1'; tr.dataset.vendorName=g.name; tr.dataset.vendorIndex=g.vendorIndex ?? '';
      const td0=document.createElement('td'); td0.textContent=''; tr.appendChild(td0);
      const tdName=document.createElement('td'); tdName.colSpan = tableId === 'actual-items' ? 6 : 5; tdName.contentEditable='true'; tdName.dataset.vendorSubtotalName='1'; tdName.dataset.vendorName=g.name; tdName.dataset.vendorIndex=g.vendorIndex ?? ''; tdName.title='업체명을 수정하면 해당 업체 품목/입고 관리/결재상신 메시지에 반영됩니다.'; tdName.textContent=`합계금액(${g.name || '업체 미지정'})`;
      tdName.addEventListener('keydown', ev=>{ if(ev.key==='Enter'){ ev.preventDefault(); tdName.blur(); } });
      tdName.addEventListener('blur', ()=>{
        const m = clean(tdName.innerText).match(/\((.*)\)/);
        const newName = (m && clean(m[1])) ? clean(m[1]) : (clean(tdName.innerText).replace(/^합계금액\s*/,'').replace(/^[:：\-–—]/,'') || '업체 미지정');
        window.deverpApplyVendorSubtotalName(tableId, g.vendorIndex ?? '', g.name || '', newName);
      });
      tr.appendChild(tdName);
      const tdAmt=document.createElement('td'); tdAmt.textContent=fmt(g.total); tr.appendChild(tdAmt);
      const tdAxis=document.createElement('td'); tdAxis.textContent=''; tr.appendChild(tdAxis);
      const tdCount=document.createElement('td'); tdCount.textContent=`${g.rows.length}개 품목`; tr.appendChild(tdCount);
      last.insertAdjacentElement('afterend', tr);
    });
    renumber221(tableId);
  };

  function ensureActualTable(){
    const table=document.getElementById('actual-items'); if(!table) return;
    const headRow=table.querySelector('thead tr');
    if(headRow && !Array.from(headRow.children).some(th=>clean(th.innerText)==='업체명')){
      const th=document.createElement('th'); th.textContent='업체명'; headRow.appendChild(th);
    }
    itemRows('actual-items').forEach(ensureActualVendorCell);
    try{ deverpRenderVendorSubtotalRows('actual-items'); }catch(e){}
  }
  function toggleActualDiffVisual(){
    const label=document.querySelector('.actual-diff-toggle'); const chk=document.getElementById('actual-diff');
    if(label && chk) label.classList.toggle('checked', !!chk.checked);
  }
  document.addEventListener('change', ev=>{
    if(ev.target && ev.target.id === 'actual-diff'){
      toggleActualDiffVisual();
      setTimeout(()=>{ ensureActualTable(); if(ev.target.checked) deverpRenderVendorSubtotalRows('actual-items'); }, 0);
    }
  });
  document.addEventListener('input', ev=>{
    const table=ev.target && ev.target.closest ? ev.target.closest('table') : null;
    const tr=ev.target && ev.target.closest ? ev.target.closest('tr') : null;
    if(table && table.id==='actual-items' && tr && !isVendorTotalRow(tr)){
      ensureActualVendorCell(tr);
      if(ev.target === tr.children[9]) tr.dataset.vendorName = clean(tr.children[9].innerText);
      setTimeout(()=>deverpRenderVendorSubtotalRows('actual-items'), 0);
    }
  });
  function start(){ ensureActualTable(); toggleActualDiffVisual(); try{ deverpRenderVendorSubtotalRows('pr-items'); }catch(e){} }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
