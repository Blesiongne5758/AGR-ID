/* =====================================================================
   AGR.ID — Frontend SPA statis (InfinityFree htdocs)
   Backend : api.php (gateway) -> Supabase PostgREST + Cloudinary
   Token sesi disimpan localStorage, dikirim via header X-Agr-Token.
   Katalog master (MASTER/SUBS/NONHALAL/TICKER) dimuat dari data-master.js.
   ===================================================================== */
'use strict';
const API = (window.AGR_API_BASE || '') + '/api.php';
const S = {
  get token(){ return localStorage.getItem('agr_token')||'' },
  set token(v){ v?localStorage.setItem('agr_token',v):localStorage.removeItem('agr_token') },
  get user(){ try{ return JSON.parse(localStorage.getItem('agr_user')||'null') }catch(e){return null} },
  set user(v){ v?localStorage.setItem('agr_user',JSON.stringify(v)):localStorage.removeItem('agr_user') },
};
async function api(action, opts={}){
  const o = { headers:{ 'Content-Type':'application/json' } };
  if(S.token) o.headers['X-Agr-Token']=S.token;
  if(opts.method) o.method=opts.method;
  if(opts.body!==undefined) o.body=JSON.stringify(opts.body);
  const url = API + '?action=' + encodeURIComponent(action) + (opts.qs?('&'+opts.qs):'');
  const r = await fetch(url,o);
  let j; try{ j = await r.json(); }catch(e){ throw new Error('Respons server tidak valid (cek config.php / hosting)'); }
  if(!r.ok || j.ok===false) throw new Error(j.error||('HTTP '+r.status));
  return j;
}
const rp = n => 'Rp ' + Number(n||0).toLocaleString('id-ID');
const esc = s => String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fotoP = p => {
  if(!p.foto) return '';
  if(/^https?:\/\//.test(p.foto)) return p.foto;            // URL lengkap (mis. seed demo)
  const cn = (typeof CLOUD_NAME!=='undefined'&&CLOUD_NAME)?CLOUD_NAME:(window.CLOUD_NAME||'');
  return 'https://res.cloudinary.com/'+(cn||'demo')+'/image/upload/w_600,f_auto,q_auto/'+encodeURIComponent(p.foto);
};

/* ==================== ROUTER SPA ==================== */
const $ = s => document.querySelector(s);
const el = (t,c,h) => { const e=document.createElement(t); if(c)e.className=c; if(h!=null)e.innerHTML=h; return e; };
const toast = m => { const t=el('div','agr-toast',esc(m)); $('#toasts').appendChild(t); setTimeout(()=>t.remove(),4200); };
const STATUS_LBL = { dp_pending:'Menunggu DP', dp_paid:'DP Dibayar', menunggu_approval:'Menunggu Approval Penjual', lunas:'Lunas', dikirim:'Dikirim', completed:'Selesai', dibatalkan:'Dibatalkan', menunggu:'Menunggu', diterima:'Diterima', ditolak:'Ditolak' };
const badge = st => `<span class="badge b-${st||'menunggu'}">${esc(STATUS_LBL[st]||st)}</span>`;

const routes = { '#/beranda':'home', '#/marketplace':'market', '#/login':'login', '#/daftar':'register', '#/chat':'chat', '#/akun':'akun',
  '#/dashboard':'dash', '#/dashboard/penjual':'dashPenjual', '#/dashboard/pembeli':'dashPembeli', '#/dashboard/admin':'dashAdmin',
  '#/produk-baru':'formProduk' };
function resolve(){
  const raw = location.hash.split('?')[0];
  const md = raw.match(/^#\/produk\/(\d+)$/);
  if(md){ tampilDetail(md[1]); return; }
  const key = Object.keys(routes).sort((a,b)=>b.length-a.length).find(k => raw.startsWith(k)) ?? '';
  const view = key ? routes[key] : 'home';
  const qs = new URLSearchParams(location.hash.split('?')[1]||'');
  const prot = ['dash','dashPenjual','dashPembeli','dashAdmin','formProduk'];
  if(prot.includes(view) && !S.token){ location.hash='#/login'; return; }
  (renderers[view]||renderers.home)(qs);
}
window.addEventListener('hashchange', resolve);
document.addEventListener('DOMContentLoaded', ()=>{ initChrome(); resolve(); loadFooter(); });

function initChrome(){
  const tk = (typeof TICKER!=='undefined'?TICKER:[]).map(([n,h,p])=>`<span class="tk"><b>${esc(n)}</b> ${rp(h)} <i class="${p>=0?'up':'down'}">${p>=0?'▲':'▼'} ${Math.abs(p)}%</i></span>`).join('<span class="tk-sep">•</span>');
  $('#ticker').innerHTML = `<div class="tk-track">${tk}${tk}</div>`;
  if(!localStorage.getItem('agr_sk_ok')) $('#skModal').classList.add('show');
  $('#skAccept').onclick = ()=>{ localStorage.setItem('agr_sk_ok','1'); $('#skModal').classList.remove('show'); };
  $('#skReject').onclick = ()=>{ $('#skModal').classList.remove('show'); };
  updateNav();
}
async function loadFooter(){
  try{
    const sets = await api('settings');
    const g=k=>{const s=sets.find(x=>x.key===k);return s?s.value:''};
    if(g('footer_tagline')) $('#fTagline').textContent=g('footer_tagline');
    if(g('footer_email')) $('#fEmail').textContent=g('footer_email');
    if(g('footer_wa')) $('#fWa').textContent=g('footer_wa');
    if(g('footer_alamat')) $('#fAlamat').textContent=g('footer_alamat');
    if(g('footer_copy')) $('#fCopy').textContent=g('footer_copy');
  }catch(e){/* footer statis default tetap tampil */}
}
function updateNav(){
  const u=S.user;
  $('#navAuth').innerHTML = u
    ? `<a class="btn btn-ghost" href="#/dashboard/${u.role}">Dashboard</a><a class="btn btn-ghost" href="#/akun" title="Ganti password">⚙️ Akun</a><button class="btn btn-outline" id="btnLogout">Keluar</button>`
    : `<a class="btn btn-ghost" href="#/login">Masuk</a><a class="btn btn-primary" href="#/daftar">Daftar</a>`;
  const bl=$('#btnLogout'); if(bl) bl.onclick=async()=>{ try{await api('logout',{method:'POST'})}catch(e){} S.token='';S.user=null;updateNav();location.hash='#/beranda'; };
}

/* ==================== VIEWS ==================== */
const renderers = {};

renderers.home = async () => {
  let prods=[]; try{ prods = await api('products',{qs:'limit=8'}); }catch(e){}
  $('#app').innerHTML = `
  <section class="hero">
    <h1>Marketplace Pertanian, Perkebunan, Perikanan &amp; Peternakan</h1>
    <p>Langsung dari petani dan peternak — penawaran harga, booking dengan DP pengikat, pengiriman terjadwal, dan ketelusuran berbasis bukti foto + GPS. Didukung AI assistant.</p>
    <div class="hero-actions"><a class="btn btn-primary btn-lg" href="#/marketplace">Jelajahi Produk</a><a class="btn btn-outline btn-lg" href="#/daftar">Jadi Penjual</a></div>
  </section>
  <section class="cats">
    ${Object.keys(SUBS).map(k=>`<a class="cat-card" href="#/marketplace?kategori=${encodeURIComponent(k)}"><h3>${k}</h3><p>${(SUBS[k]||[]).join(' · ')}</p></a>`).join('')}
  </section>
  <section><h2 class="sec-title">Produk Terbaru</h2><div class="grid">${prods.map(cardProduk).join('')||'<p class="muted">Belum ada produk — jalankan supabase-schema.sql + seed-supabase.sql di Supabase terlebih dahulu.</p>'}</div></section>`;
  bindKartu();
};

function cardProduk(p){
  const nh = NONHALAL.includes(p.sub_kategori);
  return `<div class="card prod" data-id="${p.id}">
    ${fotoP(p)?`<img loading="lazy" src="${fotoP(p)}" alt="${esc(p.nama_product)}">`:`<div class="ph">🌾</div>`}
    <div class="card-b">
      <div class="row1"><h3>${esc(p.nama_product)}</h3>${nh?'<span class="badge b-haram">⚠️ Non Halal</span>':''}</div>
      <p class="muted">${esc(p.kategori)} › ${esc(p.sub_kategori||'-')} · ${esc(p.jenis||'')}</p>
      <p class="price">${rp(p.harga)}<small> /${esc(p.satuan)}</small></p>
      <p class="muted">Stok: ${p.stok} · 📍 ${esc(p.alamat_lahan||'-')}</p>
      <button class="btn btn-primary btn-sm liat" data-id="${p.id}">Lihat &amp; Tawar</button>
    </div></div>`;
}
function bindKartu(){ document.querySelectorAll('.liat').forEach(b=>b.onclick=()=>location.hash=`#/produk/${b.dataset.id}`); }

renderers.market = async (qs) => {
  const kat = qs.get('kategori')||'', sub = qs.get('sub')||'', q = qs.get('q')||'';
  const prm = {...(kat&&{kategori:kat}),...(sub&&{sub_kategori:sub}),...(q&&{q})};
  let p=[]; try{ p = await api('products',{qs:new URLSearchParams(prm).toString()}); }catch(e){toast(e.message);}
  $('#app').innerHTML = `
  <div class="mk-head"><h2>Marketplace</h2><input id="mq" class="input" placeholder="Cari produk… (mis. cabai, nila, kopi)" value="${esc(q)}"></div>
  <div class="chips">
    <a class="chip ${!kat?'on':''}" href="#/marketplace">Semua</a>
    ${Object.keys(SUBS).map(k=>`<a class="chip ${k===kat?'on':''}" href="#/marketplace?kategori=${encodeURIComponent(k)}">${k}</a>`).join('')}
  </div>
  ${kat?`<div class="chips">${(SUBS[kat]||[]).map(s=>`<a class="chip ${s===sub?'on':''}" href="#/marketplace?kategori=${encodeURIComponent(kat)}&sub=${encodeURIComponent(s)}">${s}${NONHALAL.includes(s)?' ⚠️':''}</a>`).join('')}</div>`:''}
  <div class="grid" id="mkGrid">${p.map(cardProduk).join('')||'<p class="muted">Tidak ada produk pada filter ini.</p>'}</div>`;
  bindKartu();
  $('#mq').onkeydown = e=>{ if(e.key==='Enter') location.hash=`#/marketplace?q=${encodeURIComponent($('#mq').value)}`; };
};

async function tampilDetail(id){
  let p; try{ p = await api('product',{qs:'id='+id}); }catch(e){ toast(e.message); return; }
  const nh = NONHALAL.includes(p.sub_kategori);
  let fav=false; if(S.user&&S.user.role==='pembeli'){ try{ const fs=await api('favorites'); fav=fs.some(f=>f.target_type==='produk'&&+f.target_id===+id);}catch(e){} }
  $('#app').innerHTML = `
  <div class="detail">
    <div class="d-img">${fotoP(p)?`<img src="${fotoP(p)}">`:`<div class="ph big">🌾</div>`}</div>
    <div class="d-info">
      <h2>${esc(p.nama_product)} ${nh?'<span class="badge b-haram">⚠️ Non Halal</span>':''}</h2>
      <p class="muted">${esc(p.kategori)} › ${esc(p.sub_kategori||'-')} · Jenis: ${esc(p.jenis||'-')}</p>
      <p class="price xl">${rp(p.harga)}<small> /${esc(p.satuan)}</small></p>
      <p>${esc(p.deskripsi||'')}</p>
      <div class="sellerbox"><b>${esc((p.seller&&p.seller.nama)||'Penjual')}</b> <span class="badge b-role">${esc((p.seller&&p.seller.tipe)||'Perorangan')}</span>
        <p class="muted">📍 ${esc(p.alamat_lahan||(p.seller&&p.seller.alamat)||'-')} ${p.lat?`· <a target="_blank" rel="noopener" href="https://maps.google.com/?q=${p.lat},${p.lng}">lihat peta</a>`:''}</p></div>
      <div class="d-act">
        ${S.user&&S.user.role==='pembeli'?`<button class="btn btn-primary" id="btnTawar">Buat Penawaran</button>
          <button class="btn btn-outline" id="btnFav">${fav?'★':'☆'} Favorit</button>`:!S.user?`<a class="btn btn-primary" href="#/login">Masuk untuk Menawar</a>`:'<span class="muted">Hanya pembeli yang dapat membuat penawaran.</span>'}
      </div>
      <div id="offerBox"></div>
    </div></div>`;
  const bf=$('#btnFav'); if(bf) bf.onclick=async()=>{ try{ const r=await api('favorite-toggle',{method:'POST',body:{target_type:'produk',target_id:+id}}); bf.innerHTML=(r.favorit?'★':'☆')+' Favorit'; toast(r.favorit?'Ditambahkan ke favorit':'Dihapus dari favorit'); }catch(e){toast(e.message);} };
  const bt=$('#btnTawar'); if(bt) bt.onclick=()=>{
    $('#offerBox').innerHTML = `<div class="panel"><h4>Buat Penawaran Harga</h4>
      <label>Harga tawar per ${esc(p.satuan)} (Rp)<input id="oHarga" class="input" type="number" value="${Math.round(p.harga*0.95)}"></label>
      <label>Jumlah (${esc(p.satuan)})<input id="oJml" class="input" type="number" value="10" min="1"></label>
      <label>Catatan<textarea id="oNote" class="input" rows="2" placeholder="Contoh: kirim Jumat, kualitas grade A"></textarea></label>
      <button class="btn btn-primary" id="oSend">Kirim Penawaran</button></div>`;
    $('#oSend').onclick=async()=>{ try{ await api('offer-create',{method:'POST',body:{product_id:+id,harga_tawar:+$('#oHarga').value,jumlah:+$('#oJml').value,catatan:$('#oNote').value}}); toast('Penawaran terkirim — pantau respons penjual di Dashboard Pembeli.'); $('#offerBox').innerHTML=''; }catch(e){toast(e.message);} };
  };
}

renderers.login = () => {
  $('#app').innerHTML = `<div class="auth card-form"><h2>Masuk ke AGR.ID</h2>
    <label>Email / Username<input id="le" class="input" type="text" autocomplete="username" placeholder="nama@email.com"></label>
    <label>Password<input id="lp" class="input" type="password" autocomplete="current-password" placeholder="••••••••"></label>
    <button class="btn btn-primary wide" id="lgo">Masuk</button>
    <p class="muted center">Belum punya akun? <a href="#/daftar">Daftar di sini</a></p></div>`;
  // Perbaikan kompatibilitas: pastikan input password dapat diketik/diisi autofill
  // (beberapa browser tidak mengisi field yang dibuat tanpa form & label `for`).
  const lp = $('#lp'); lp.setAttribute('name', 'password'); lp.label = null;
  $('#lgo').onclick=doLogin;
  $('#le').onkeydown=e=>{ if(e.key==='Enter'){ e.preventDefault(); lp.focus(); } };
  lp.onkeydown=e=>{ if(e.key==='Enter'){ e.preventDefault(); doLogin(); } };
};
async function doLogin(){
  const iden=$('#le').value.trim(), pass=$('#lp').value;
  if(!iden){ toast('Email/username wajib diisi'); $('#le').focus(); return; }
  if(pass.length<6){ toast('Password minimal 6 karakter — periksa Caps Lock / spasi'); $('#lp').focus(); return; }
  try{ const r = await api('login',{method:'POST',body:{email:iden,password:pass}});
    S.token=r.token; S.user=r.user; updateNav(); toast('Selamat datang, '+r.user.nama+'!'); location.hash='#/dashboard/'+r.user.role;
  }catch(e){ toast(e.message); }
}

renderers.register = () => {
  $('#app').innerHTML = `<div class="auth card-form"><h2>Pendaftaran AGR.ID</h2>
    <div class="seg" id="segRole"><button class="on" data-r="penjual">Saya Penjual</button><button data-r="pembeli">Saya Pembeli</button></div>
    <label>Nama / Nama Usaha<input id="rn" class="input" autocomplete="name"></label>
    <label>Email<input id="re" class="input" type="email" autocomplete="email"></label>
    <div class="rel"><label>Password (min. 8 karakter)<input id="rpw" class="input" type="password" name="password" autocomplete="new-password"></label>
      <button type="button" class="btn btn-outline btn-sm pwd-eye" data-for="rpw" title="Tampilkan/sembunyikan">👁</button></div>
    <div class="pw-meter"><i id="pwBar"></i></div><small id="pwHint" class="muted">Gunakan generator: <button type="button" class="btn btn-outline btn-sm" id="pwGen">🔐 Buat Password Kuat</button></small>
    <label>No. HP<input id="rhp" class="input"></label>
    <label>Tipe <select id="rtipe" class="input"></select></label>
    <div id="corpFields" style="display:none"><label>NPWP<input id="rnpwp" class="input"></label><label>NIB<input id="rnib" class="input"></label></div>
    <label>Alamat lengkap<textarea id="ralamat" class="input" rows="2"></textarea></label>
    <div class="gps-row"><button class="btn btn-outline btn-sm" id="rgps">📍 Deteksi Koordinat GPS</button><span id="rgpsv" class="muted">belum diisi</span></div>
    <label class="chk"><input type="checkbox" id="rsksaya"> Saya menyetujui Syarat &amp; Ketentuan</label>
    <button class="btn btn-primary wide" id="rgo">Daftar</button>
    <p class="muted center">Sudah punya akun? <a href="#/login">Masuk</a></p></div>`;
  let role='penjual';
  const chkTipe=()=>{ $('#corpFields').style.display=(['Yayasan','Koperasi','Perusahaan','Kelompok/Paguyuban'].includes($('#rtipe').value))?'block':'none'; };
  const isiSeg=()=>{ $('#rtipe').innerHTML=(role==='penjual'?['Perorangan','Kelompok/Paguyuban','Koperasi','Perusahaan']:['Perorangan','Yayasan','Koperasi','Perusahaan']).map(t=>`<option>${t}</option>`).join(''); chkTipe(); };
  isiSeg();
  $('#segRole').querySelectorAll('button').forEach(b=>b.onclick=()=>{ role=b.dataset.r; $('#segRole').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b)); isiSeg(); });
  $('#rtipe').onchange=chkTipe;
  // ---- helper password: toggle lihat, strength meter, generator kuat ----
  document.querySelectorAll('.pwd-eye').forEach(b=>b.onclick=()=>{ const i=$('#'+b.dataset.for); i.type = i.type==='password'?'text':'password'; });
  const pwScore=v=>{ let s=0; if(v.length>=8)s++; if(/[a-z]/.test(v)&&/[A-Z]/.test(v))s++; if(/\d/.test(v))s++; if(/[^A-Za-z0-9]/.test(v))s++; if(v.length>=12)s++; return Math.min(s,5); };
  const pwWarn=v=>{ const w=[]; if(v.length<8)w.push('min. 8 karakter'); if(!/[A-Z]/.test(v))w.push('huruf besar'); if(!/[a-z]/.test(v))w.push('huruf kecil'); if(!/\d/.test(v))w.push('angka'); if(!/[^A-Za-z0-9]/.test(v))w.push('simbol'); return w; };
  $('#rpw').oninput=()=>{ const v=$('#rpw').value, s=pwScore(v), bar=$('#pwBar');
    bar.style.width=(s*20)+'%'; bar.className='lvl'+s;
    $('#pwHint').textContent = v?('Kekuatan: '+['Sangat Lemah','Lemah','Cukup','Baik','Kuat','Sangat Kuat'][s]+(s<4?' — kurang: '+pwWarn(v).join(', '):' ✓')):'Gunakan generator:'; };
  $('#pwGen').onclick=async()=>{ const a='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*_-+=?';
    let out=''; const rnd=arr=>crypto.getRandomValues(arr); const buf=new Uint32Array(16); rnd(buf);
    for(let i=0;i<16;i++) out+=a[buf[i]%a.length];
    out=out.slice(0,3)+'!'+out.slice(3)+'9'; // jamin simbol & angka
    $('#rpw').value=out; $('#rpw').dispatchEvent(new Event('input'));
    try{ await navigator.clipboard.writeText(out); toast('Password kuat dibuat & disalin — simpan baik-baik!'); }catch(e){ toast('Password kuat dibuat — salin manual dari kolom.'); } };

  $('#rgps').onclick=()=>{ if(!navigator.geolocation){toast('Browser tidak mendukung geolokasi');return;}
    navigator.geolocation.getCurrentPosition(pos=>{ window._lat=pos.coords.latitude; window._lng=pos.coords.longitude; $('#rgpsv').textContent=`${window._lat.toFixed(6)}, ${window._lng.toFixed(6)}`; },()=>toast('Izin geolokasi ditolak')); };
  $('#rgo').onclick=async()=>{
    if(!$('#rsksaya').checked){ toast('Setujui Syarat & Ketentuan terlebih dahulu'); return; }
    const pw=$('#rpw').value;
    if(pw.length<8||pwScore(pw)<3){ toast('Password terlalu lemah — minimal 8 karakter dengan huruf besar, angka & simbol (pakai generator 🔐)'); $('#rpw').focus(); return; }
    try{ await api('register',{method:'POST',body:{email:$('#re').value.trim(),password:pw,nama:$('#rn').value,role,tipe:$('#rtipe').value,alamat:$('#ralamat').value,no_hp:$('#rhp').value,npwp:$('#rnpwp').value||'',nib:$('#rnib').value||'',lat:window._lat??null,lng:window._lng??null}});
      toast('Pendaftaran berhasil, silakan Masuk'); location.hash='#/login';
    }catch(e){ toast(e.message); } };
};

/* ---- GANTI PASSWORD untuk semua user (penjual/pembeli/admin) ---- */
renderers.akun = () => {
  if(!S.user){ location.hash='#/login'; return; }
  $('#app').innerHTML = `<div class="auth card-form"><h2>Pengaturan Akun — ${esc(S.user.nama)}</h2>
    <p class="muted small">Login memakai email/username: <b>${esc(S.user.email)}</b></p>
    <label>Password Lama<div class="rel"><input id="kOld" class="input" type="password" autocomplete="current-password"><button type="button" class="btn btn-outline btn-sm pwd-eye" data-for="kOld">👁</button></div></label>
    <label>Password Baru (min. 8 karakter)<div class="rel"><input id="kNew" class="input" type="password" autocomplete="new-password"><button type="button" class="btn btn-outline btn-sm pwd-eye" data-for="kNew">👁</button></div></label>
    <div class="pw-meter"><i id="kBar"></i></div>
    <label>Konfirmasi Password Baru<input id="kNew2" class="input" type="password" autocomplete="new-password"></label>
    <button class="btn btn-primary wide" id="kSave">Simpan Password</button></div>`;
  document.querySelectorAll('.pwd-eye').forEach(b=>b.onclick=()=>{ const i=$('#'+b.dataset.for); i.type=i.type==='password'?'text':'password'; });
  const score=v=>{ let s=0; if(v.length>=8)s++; if(/[a-z]/.test(v)&&/[A-Z]/.test(v))s++; if(/\d/.test(v))s++; if(/[^A-Za-z0-9]/.test(v))s++; if(v.length>=12)s++; return Math.min(s,5); };
  $('#kNew').oninput=()=>{ const v=$('#kNew').value,s=score(v); $('#kBar').style.width=(s*20)+'%'; $('#kBar').className='lvl'+s; };
  $('#kSave').onclick=async()=>{
    if($('#kNew').value!==$('#kNew2').value){ toast('Konfirmasi password tidak sama'); return; }
    if(score($('#kNew').value)<3){ toast('Password baru terlalu lemah — tambahkan huruf besar/angka/simbol'); return; }
    try{ await api('change-password',{method:'POST',body:{old_password:$('#kOld').value,new_password:$('#kNew').value}});
      toast('Password berhasil diganti'); $('#kOld').value=$('#kNew').value=$('#kNew2').value=''; }catch(e){toast(e.message);} };
};

renderers.chat = () => {
  $('#app').innerHTML = `<div class="chatbox card"><h2>🤖 AI Assistant AGR.ID</h2><div id="msgs" class="msgs"></div>
    <div class="chat-in"><input id="cin" class="input" placeholder="Tanya: cara posting cabai merah, cari produk ikan air tawar…"><button class="btn btn-primary" id="csnd">Kirim</button></div>
    <p class="muted small">Mode aturan lokal aktif. Untuk jawaban LLM penuh, hubungkan backend Flask via config.php (AGR_ID_API_URL).</p></div>`;
  msg('Halo! Saya asisten AGR.ID. Saya bisa membantu mengisi informasi produk atau mencari produk yang Anda butuhkan. Coba: “cara jual cabai” atau “cari ikan nila”.');
  const send=()=>{ const v=$('#cin').value.trim(); if(!v)return; msg(v,'me'); $('#cin').value=''; botJawab(v); };
  $('#csnd').onclick=send; $('#cin').onkeydown=e=>e.key==='Enter'&&send();
};
function msg(t,who){ const d=el('div','m'+(who==='me'?' me':''),esc(t).replace(/\n/g,'<br>')); $('#msgs').appendChild(d); $('#msgs').scrollTop=1e9; }
function botJawab(t){
  const s=t.toLowerCase(); let r='';
  const cari = MASTER.filter(x=>s.includes(x.n.toLowerCase())).slice(0,6);
  if(/cari|butuh|beli/.test(s)&&cari.length){ r='Produk cocok di master katalog:\n'+cari.map(x=>`• ${x.n} (${x.k} › ${x.s}) — jenis: ${x.j}`).join('\n')+'\nBuka Marketplace untuk stok & harga.'; }
  else if(/jual|posting|upload|produk/i.test(s)){ r='Cara menjual: 1) Daftar sebagai Penjual (Perorangan/Koperasi/Paguyuban), 2) Dashboard Penjual → “＋ Produk Baru”, 3) Pilih kategori & sub kategori, ketik nama produk (auto-lengkapi dari master DB), 4) Upload foto (langsung ke Cloudinary), 5) Aktifkan GPS lahan. Pembeli lalu dapat mengirim penawaran harga.'; }
  else if(/dp|booking|ikat/.test(s)){ r='Booking memakai DP (persen diatur admin, bawaan 20%) sebagai pengikat. Metode: Tunai/Transfer Bank/QRIS. Setelah DP, pembeli mengunggah bukti pelunasan → approval penjual → status Lunas → barang dikirim.'; }
  else if(/ekspedisi|kirim/.test(s)){ r='Jadwal dipilih saat booking; kurir (Agribus Cargo/JNE Logistics/SiCepat Cold Chain) dicatat via tracking code. Setiap tahap (panen→sortasi→pengemasan→pengiriman→penerimaan) diunggah sebagai eviden foto + koordinat GPS.'; }
  else if(/halal/.test(s)){ r='Sub kategori Babi (Peternakan) diberi label ⚠️ NON HALAL dan dapat disaring pada marketplace.'; }
  else if(/bayar|payment|qris/.test(s)){ r='Pembayaran via payment gateway (QRIS/VA/e-wallet). Pada InfinityFree, integrasi Midtrans/Xendit berjalan lewat bridge backend Flask — lihat DEPLOY-INFINITYFREE.md.'; }
  else r='Saya bantu! Coba: “cara jual cabai merah”, “cari produk ikan air laut”, “apa itu DP booking?”, “bagaimana ekspedisinya?”.';
  setTimeout(()=>msg(r),350);
}

function butuhRole(...roles){ if(!S.user||!roles.includes(S.user.role)){ toast('Perlu login sebagai '+roles.join('/')); location.hash='#/login'; return false; } return true; }
renderers.dash = () => { if(S.user) location.hash='#/dashboard/'+S.user.role; else location.hash='#/login'; };

renderers.dashPenjual = async () => {
  if(!butuhRole('penjual','admin')) return;
  const [prods,offers,tx,pel] = await Promise.all([
    api('products',{qs:'seller='+S.user.id}).catch(()=>[]),
    api('offers-mine').catch(()=>[]),
    api('transactions',{qs:'side=penjualan'}).catch(()=>[]),
    api('pelunasan-list').catch(()=>[])
  ]);
  const omzet = tx.filter(t=>['lunas','completed'].includes(t.status)).reduce((a,t)=>a+ +t.harga_total,0);
  $('#app').innerHTML = `<h2>Dashboard Penjual</h2>
   <div class="stats"><div class="stat"><b>${prods.length}</b>Produk aktif</div><div class="stat"><b>${offers.filter(o=>o.status==='menunggu').length}</b>Penawaran masuk</div><div class="stat"><b>${pel.length}</b>Antrean approval</div><div class="stat"><b>${rp(omzet)}</b>Omzet lunas</div></div>
   <div class="tabs" id="tabsP"><button class="on" data-t="prod">Produk Saya</button><button data-t="ofr">Penawaran</button><button data-t="pln">Approval Pelunasan</button><button data-t="rpt">Laporan Penjualan</button></div>
   <div id="tabP"></div>`;
  const show=t=>{ $('#tabsP').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
    const box=$('#tabP');
    if(t==='prod') box.innerHTML=`<a class="btn btn-primary mb" href="#/produk-baru">＋ Produk Baru</a><div class="grid">${prods.map(cardProduk).join('')||'<p class="muted">Belum ada produk.</p>'}</div>`;
    if(t==='ofr') box.innerHTML=tbl(['Produk','Tawaran','Jumlah','Status','Aksi'],offers.map(o=>{
      const pr=prods.find(p=>p.id===o.product_id)||{};
      return [pr.nama_product||('#'+o.product_id),rp(o.harga_tawar)+'/'+esc(pr.satuan||'unit'),o.jumlah,badge(o.status),
        o.status==='menunggu'?`<button class="btn btn-sm btn-primary tr" data-id="${o.id}">Terima</button> <button class="btn btn-sm btn-danger tol" data-id="${o.id}">Tolak</button>`:''];})) || '<p class="muted">Belum ada penawaran masuk.</p>';
    if(t==='pln') box.innerHTML=tbl(['Transaksi','Total','DP','Catatan','Bukti','Keputusan'],pel.map(x=>[`TX-${x.id}`,rp(x.harga_total),rp(x.dp),esc(x.catatan_pelunasan||'-'),x.bukti_transfer?`<a href="#" class="lbukti" data-bukti="${esc(x.bukti_transfer)}">Lihat bukti</a>`:'<span class="muted">(tanpa file)</span>',
      `<button class="btn btn-sm btn-primary ok" data-id="${x.id}">Setuju</button> <button class="btn btn-sm btn-danger no" data-id="${x.id}">Tolak</button>`])) || '<p class="muted">Tidak ada antrean pelunasan.</p>';
    if(t==='rpt') box.innerHTML=tbl(['ID','Total','Potongan Platform','Status','Tanggal'],tx.map(x=>[x.id,rp(x.harga_total),rp(x.potongan_platform||0),badge(x.status),(x.created_at||'').slice(0,10)])) || '<p class="muted">Belum ada transaksi.</p>';
    bindKartu();
    box.querySelectorAll('.tr,.tol').forEach(b=>b.onclick=async()=>{ try{ await api('offer-respond',{method:'POST',body:{id:+b.dataset.id,status:b.classList.contains('tr')?'terima':'ditolak'}}); toast('Penawaran '+b.textContent.toLowerCase()); renderers.dashPenjual(); }catch(e){toast(e.message);} });
    box.querySelectorAll('.ok,.no').forEach(b=>b.onclick=async()=>{ try{ await api('pelunasan-respond',{method:'POST',body:{transaction_id:+b.dataset.id,keputusan:b.classList.contains('ok')?'setuju':'tolak'}}); toast('Pelunasan '+b.textContent.toLowerCase()); renderers.dashPenjual(); }catch(e){toast(e.message);} });
    box.querySelectorAll('.lbukti').forEach(a=>a.onclick=async e=>{ e.preventDefault(); try{ const r=await api('media-private-url',{qs:'public_id='+encodeURIComponent(a.dataset.bukti)}); window.open(r.url,'_blank'); }catch(err){toast(err.message);} });
  };
  $('#tabsP').querySelectorAll('button').forEach(b=>b.onclick=()=>show(b.dataset.t)); show('prod');
};

renderers.dashPembeli = async () => {
  if(!butuhRole('pembeli','admin')) return;
  const [ofr,tx,favs] = await Promise.all([api('offers-mine').catch(()=>[]),api('transactions',{qs:'side=pembelian'}).catch(()=>[]),api('favorites').catch(()=>[])]);
  $('#app').innerHTML = `<h2>Dashboard Pembeli</h2>
   <div class="stats"><div class="stat"><b>${ofr.filter(o=>o.status==='diterima').length}</b>Penawaran diterima</div><div class="stat"><b>${tx.filter(t=>t.status==='menunggu_approval').length}</b>Menunggu penjual</div><div class="stat"><b>${tx.filter(t=>t.status==='completed').length}</b>Selesai</div><div class="stat"><b>${favs.length}</b>Favorit</div></div>
   <div class="tabs" id="tabsB"><button class="on" data-t="ofr">Penawaran Saya</button><button data-t="trx">Transaksi & Pelunasan</button><button data-t="rpt">Laporan Pembelian</button><button data-t="fav">Favorit</button></div><div id="tabB"></div>`;
  const show=t=>{ $('#tabsB').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.t===t)); const box=$('#tabB');
    if(t==='ofr') box.innerHTML=tbl(['ID','Tawaran','Jumlah','Status','Aksi'],ofr.map(o=>[o.id,rp(o.harga_tawar),o.jumlah,badge(o.status),
      o.status==='diterima'?`<button class="btn btn-sm btn-primary bk" data-id="${o.id}" data-h="${o.harga_tawar}" data-j="${o.jumlah}">Booking + DP</button>`:''])) || '<p class="muted">Belum ada penawaran. Kirim penawaran dari halaman produk.</p>';
    if(t==='trx') box.innerHTML=tbl(['ID','Total','DP','Metode','Status','Aksi'],tx.map(x=>{ const aksi=[];
      if(x.status==='dp_pending') aksi.push(`<button class="btn btn-sm btn-primary pay" data-id="${x.id}" data-dp="${x.dp}">Bayar DP</button>`);
      if(x.status==='dp_paid') aksi.push(`<button class="btn btn-sm btn-primary pay" data-id="${x.id}" data-dp="0">Upload Bukti Pelunasan</button>`);
      if(x.status==='dikirim') aksi.push(`<button class="btn btn-sm btn-success done" data-id="${x.id}">Terima & Selesai</button>`);
      if(['completed','lunas'].includes(x.status)) aksi.push(`<button class="btn btn-sm btn-outline rate" data-id="${x.id}" data-to="${x.seller_id}">★ Rating</button>`);
      return [x.id,rp(x.harga_total),rp(x.dp),esc(x.metode_bayar||'-'),badge(x.status),aksi.join(' ')];})) || '<p class="muted">Belum ada transaksi.</p>';
    if(t==='rpt') box.innerHTML=tbl(['ID','Total','DP','Platform Fee','Status','Tanggal'],tx.map(x=>[x.id,rp(x.harga_total),rp(x.dp),rp(x.potongan_platform||0),badge(x.status),(x.created_at||'').slice(0,10)])) || '<p class="muted">Belum ada laporan.</p>';
    if(t==='fav') box.innerHTML=tbl(['Tipe','Target','Aksi'],favs.map(f=>[f.target_type,'#'+f.target_id,`<a class="btn btn-sm btn-outline" href="#/produk/${f.target_id}">Buka</a>`])) || '<p class="muted">Belum ada favorit.</p>';
    box.querySelectorAll('.bk').forEach(b=>b.onclick=()=>formBooking(b,+b.dataset.h,+b.dataset.j));
    box.querySelectorAll('.pay').forEach(b=>b.onclick=()=>formBayar(+b.dataset.id,+b.dataset.dp));
    box.querySelectorAll('.done').forEach(b=>b.onclick=async()=>{ try{ await api('tx-complete',{method:'POST',body:{transaction_id:+b.dataset.id}}); toast('Transaksi selesai — beri rating penjual!'); renderers.dashPembeli(); }catch(e){toast(e.message);} });
    box.querySelectorAll('.rate').forEach(b=>b.onclick=()=>formRating(+b.dataset.id,+b.dataset.to));
  };
  $('#tabsB').querySelectorAll('button').forEach(b=>b.onclick=()=>show(b.dataset.t)); show('ofr');
};
function formBooking(btn,oid,h,j){
  const total=Math.round(h*j);
  btn.closest('td').innerHTML=`<div class="panel"><label>Metode DP<select id="bdp" class="input"><option>Transfer Bank</option><option>QRIS</option><option>Tunai</option></select></label>
   <label>Jadwal Pengiriman<input id="bdk" class="input" type="date"></label>
   <label>Ekspedisi<select id="bdx" class="input"><option>Agribus Cargo</option><option>JNE Logistics</option><option>SiCepat Cold Chain</option></select></label>
   <p class="muted">Estimasi DP ±20%: <b>${rp(Math.round(total*0.2))}</b> dari total ${rp(total)} — angka final dihitung server sesuai pengaturan admin.</p>
   <button class="btn btn-primary" id="bdgo">Booking Sekarang</button></div>`;
  $('#bdgo').onclick=async()=>{ try{ const r=await api('booking-create',{method:'POST',body:{offer_id:oid,metode_dp:$('#bdp').value,jadwal_kirim:$('#bdk').value,ekspedisi:$('#bdx').value}});
    toast(`Booking dibuat. DP ${rp(r.booking.dp)} (${r.persen_dp}%). Silakan bayar DP.`); renderers.dashPembeli(); }catch(e){toast(e.message);} };
}
function formBayar(txId,dp){
  const td=$(`.pay[data-id="${txId}"]`).closest('td');
  td.innerHTML=`<div class="panel"><p class="muted small">${dp>0?`Bayar DP <b>${rp(dp)}</b> ke rekening penjual, lalu unggah bukti (tersimpan privat di Cloudinary).`:'Unggah bukti pelunasan sisa pembayaran (privat).'}</p>
   <input type="file" id="fbFile" accept="image/*,.pdf" class="input">
   <label>Catatan<input id="fbNote" class="input" placeholder="No. ref / tanggal transfer"></label>
   <button class="btn btn-primary" id="fbGo">${dp>0?'Konfirmasi Pembayaran DP':'Kirim Bukti → Approval Penjual'}</button></div>`;
  $('#fbGo').onclick=async()=>{
    let bukti='';
    const f=$('#fbFile').files[0];
    if(f){ try{ bukti=await uploadCloud(f,'private','kyc'); }catch(e){ toast('Upload gagal: '+e.message+'. Catatan tetap terkirim.'); } }
    try{
      if(dp>0){ await api('dp-confirm',{method:'POST',body:{transaction_id:txId,bukti,ref_payment:$('#fbNote').value}}); toast('DP dikonfirmasi — status menjadi DP Dibayar.'); }
      else { await api('pelunasan-submit',{method:'POST',body:{transaction_id:txId,bukti,catatan:$('#fbNote').value}}); toast('Bukti terkirim — menunggu approval penjual.'); }
      renderers.dashPembeli();
    }catch(e){toast(e.message);}
  };
}
function formRating(txId,toUser){
  const td=$(`.rate[data-id="${txId}"]`).closest('td');
  td.innerHTML=`<div class="panel"><label>Skor kepuasan<select id="rtS" class="input">${[5,4,3,2,1].map(n=>`<option value="${n}">${'★'.repeat(n)}${'☆'.repeat(5-n)} (${n})</option>`).join('')}</select></label>
   <label>Ulasan<textarea id="rtU" class="input" rows="2" placeholder="Kualitas barang, ketepatan jadwal…"></textarea></label>
   <button class="btn btn-primary" id="rtGo">Kirim Penilaian</button></div>`;
  $('#rtGo').onclick=async()=>{ try{ await api('rate',{method:'POST',body:{transaction_id:txId,to_user:toUser,skor:+$('#rtS').value,ulasan:$('#rtU').value}}); toast('Terima kasih atas penilaiannya!'); renderers.dashPembeli(); }catch(e){toast(e.message);} };
}

renderers.formProduk = async () => {
  if(!butuhRole('penjual','admin')) return;
  $('#app').innerHTML = `<h2>Posting Produk Baru</h2><div class="card-form card">
   <label>Kategori<select id="pk" class="input">${Object.keys(SUBS).map(k=>`<option>${k}</option>`).join('')}</select></label>
   <label>Sub Kategori<select id="ps" class="input"></select></label>
   <label class="rel">Nama Produk <small class="muted">(auto-lengkapi dari master DB; nama baru otomatis tersimpan)</small>
     <input id="pn" class="input" autocomplete="off"><div id="pnl" class="sug"></div></label>
   <label>Jenis/Varietas<input id="pj" class="input" placeholder="mis. Biasa, Keriting, Rawit"></label>
   <div class="two"><label>Harga per satuan<input id="ph" class="input" type="number"></label><label>Satuan<select id="pu" class="input"><option>kg</option><option>pack</option><option>ekor</option><option>lusin</option><option>ton</option></select></label></div>
   <label>Stok<input id="pst" class="input" type="number" value="100"></label>
   <label>Deskripsi<textarea id="pd" class="input" rows="3"></textarea></label>
   <label>Foto Produk<input type="file" id="pf" accept="image/*" class="input"></label>
   <div class="gps-row"><button class="btn btn-outline btn-sm" id="pgps">📍 Deteksi GPS Lahan</button><span id="pgpsv" class="muted">belum diisi</span></div>
   <button class="btn btn-primary wide" id="psave">Simpan &amp; Tayangkan</button></div>`;
  const isiSub=()=>{ $('#ps').innerHTML=(SUBS[$('#pk').value]||[]).map(s=>`<option value="${esc(s)}">${s}${NONHALAL.includes(s)?' — ⚠️ Non Halal':''}</option>`).join(''); };
  $('#pk').onchange=isiSub; isiSub();
  $('#pn').oninput=()=>{ const v=$('#pn').value.toLowerCase();
    const hit=MASTER.filter(x=>x.n.toLowerCase().includes(v)).slice(0,8);
    $('#pnl').innerHTML=v?(hit.map(x=>`<button class="sg" data-n="${esc(x.n)}" data-k="${esc(x.k)}" data-s="${esc(x.s)}" data-j="${esc(x.j)}">${esc(x.n)} <small>${esc(x.k)} › ${esc(x.s)}</small></button>`).join('')+`<button class="sg baru" data-n="${esc($('#pn').value)}" data-k="" data-s="" data-j="">＋ Pakai “${esc($('#pn').value)}” (baru — masuk master DB)</button>`):'';
    $('#pnl').querySelectorAll('.sg').forEach(b=>b.onclick=()=>{ $('#pn').value=b.dataset.n; if(b.dataset.k===$('#pk').value&&b.dataset.s) $('#ps').value=b.dataset.s; $('#pj').value=b.dataset.j||''; $('#pnl').innerHTML=''; }); };
  $('#pgps').onclick=()=>navigator.geolocation.getCurrentPosition(p=>{window._plat=p.coords.latitude;window._plng=p.coords.longitude;$('#pgpsv').textContent=`${window._plat}, ${window._plng}`;},()=>toast('Izin GPS ditolak'));
  $('#psave').onclick=async()=>{
    if(!$('#pn').value||!$('#ph').value){ toast('Nama produk & harga wajib diisi'); return; }
    let foto=''; const f=$('#pf').files[0];
    if(f){ try{ foto=await uploadCloud(f,'public'); }catch(e){ toast('Foto gagal diupload: '+e.message); return; } }
    try{ await api('product-create',{method:'POST',body:{nama_product:$('#pn').value,jenis:$('#pj').value,kategori:$('#pk').value,sub_kategori:$('#ps').value,deskripsi:$('#pd').value,harga:+$('#ph').value,satuan:$('#pu').value,stok:+$('#pst').value,foto,lat:window._plat??null,lng:window._plng??null}});
      toast('Produk tayang! Nama baru otomatis masuk master DB.'); location.hash='#/dashboard/penjual'; }catch(e){toast(e.message);} };
};

renderers.dashAdmin = async () => {
  if(!butuhRole('admin')) return;
  let rep=[],sets=[];
  try{ rep=await api('report-admin'); }catch(e){}
  try{ sets=await api('settings'); }catch(e){}
  const setVal=k=>{const s=sets.find(x=>x.key===k);return s?s.value:''};
  $('#app').innerHTML = `<h2>Dashboard Admin</h2>
   <div class="stats"><div class="stat"><b>${rp(rep.gmv||0)}</b>GMV</div><div class="stat"><b>${rp(rep.pendapatan_platform||0)}</b>Pendapatan Platform</div><div class="stat"><b>${rep.jumlah||0}</b>Transaksi</div></div>
   <div class="tabs" id="tabsA"><button class="on" data-t="fin">Laporan Keuangan</button><button data-t="biaya">DP &amp; Biaya</button><button data-t="fitur">Toggle Fitur</button><button data-t="footer">Footer</button><button data-t="akun">Akun Admin</button></div><div id="tabA"></div>`;
  const show=t=>{ $('#tabsA').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.t===t)); const box=$('#tabA');
    if(t==='fin'){ const mx=Math.max(1,...Object.values(rep.per_bulan||{}));
      box.innerHTML='<div class="panel"><h4>GMV per Bulan</h4>'+(Object.entries(rep.per_bulan||{}).map(([m,v])=>'<div class="bar-row"><span>'+m+'</span><div class="bar"><i style="width:'+Math.min(100,v/mx*100)+'%"></i></div><b>'+rp(v)+'</b></div>').join('')||'<p class="muted">Belum ada transaksi.</p>')+'</div>'; }
    if(t==='biaya') box.innerHTML=`<div class="card-form"><label>Persen DP Booking (%)<input id="gDP" class="input" value="${esc(setVal('persen_dp')||'20')}"></label>
      <label>Biaya Penanganan (%)<input id="gFee" class="input" value="${esc(setVal('biaya_penanganan')||'2.5')}"></label>
      <label>Biaya Tambahan Flat (Rp)<input id="gFlat" class="input" value="${esc(setVal('biaya_tambahan_flat')||'0')}"></label>
      <label>Biaya Verifikasi Eviden (Rp)<input id="gVer" class="input" value="${esc(setVal('biaya_verifikasi')||'0')}"></label>
      <button class="btn btn-primary" id="gSave">Simpan Biaya</button></div>`;
    if(t==='fitur') box.innerHTML=`<div class="card-form">${[['beranda_aktif','Landing Page'],['fitur_marketplace','Marketplace & Penawaran'],['fitur_booking_dp','Booking DP'],['fitur_payment_gateway','Payment Gateway'],['fitur_eviden_gps','Eviden & Ketelusuran GPS'],['fitur_rating','Rating Kepuasan'],['fitur_favorit','Favorit Pembeli'],['fitur_chat_ai','AI Chat Agent'],['fitur_crypto','Dompet Crypto (AGR Coin)'],['fitur_storage_cloud','Cloud Storage Media']].map(([k,lbl])=>`<label class="sw"><input type="checkbox" data-k="${k}" ${setVal(k)!=='0'?'checked':''}> ${lbl}</label>`).join('')}<button class="btn btn-primary" id="fSave">Simpan Toggle</button></div>`;
    if(t==='footer') box.innerHTML=`<div class="card-form"><label>Tagline Footer<input id="fTag" class="input" value="${esc(setVal('footer_tagline'))}"></label>
      <label>Email Kontak<input id="fMail" class="input" value="${esc(setVal('footer_email'))}"></label><label>WhatsApp<input id="fWa" class="input" value="${esc(setVal('footer_wa'))}"></label>
      <label>Alamat Kantor<input id="fAddr" class="input" value="${esc(setVal('footer_alamat'))}"></label><label>Copyright<input id="fCopy" class="input" value="${esc(setVal('footer_copy'))}"></label>
      <button class="btn btn-primary" id="fkSave">Simpan Footer</button></div>`;
    if(t==='akun'){ const u=S.user||{};
      box.innerHTML=`<div class="card-form"><h4>Ganti Password Admin</h4>
        <label>Password Lama<div class="rel"><input id="aOld" class="input" type="password" autocomplete="current-password"><button type="button" class="btn btn-outline btn-sm pwd-eye" data-for="aOld">👁</button></div></label>
        <label>Password Baru (min. 8 karakter)<div class="rel"><input id="aNew" class="input" type="password" autocomplete="new-password"><button type="button" class="btn btn-outline btn-sm pwd-eye" data-for="aNew">👁</button></div></label>
        <div class="pw-meter"><i id="aBar"></i></div>
        <label>Konfirmasi Password Baru<input id="aNew2" class="input" type="password" autocomplete="new-password"></label>
        <button class="btn btn-primary" id="aPwSave">Simpan Password</button>
        <p class="muted small mt-1">Login admin dapat memakai email maupun username: <b>${esc(u.email||'test@gmail.com')}</b></p></div>`;
      box.querySelectorAll('.pwd-eye').forEach(b=>b.onclick=()=>{ const i=$('#'+b.dataset.for); i.type=i.type==='password'?'text':'password'; });
      $('#aNew').oninput=()=>{ const v=$('#aNew').value,s=pwScore(v); $('#aBar').style.width=(s*20)+'%'; $('#aBar').className='lvl'+s; };
      $('#aPwSave').onclick=async()=>{
        if($('#aNew').value!==$('#aNew2').value){ toast('Konfirmasi password tidak sama'); return; }
        if(pwScore($('#aNew').value)<3){ toast('Password baru terlalu lemah — pakai generator/huruf besar+angka+simbol'); return; }
        try{ await api('change-password',{method:'POST',body:{old_password:$('#aOld').value,new_password:$('#aNew').value}});
          toast('Password admin berhasil diganti'); $('#aOld').value=$('#aNew').value=$('#aNew2').value=''; }catch(e){toast(e.message);} };
    }
    const sv=async(obj,reload)=>{ try{ await api('settings',{method:'POST',body:obj}); toast('Pengaturan disimpan'); if(reload) loadFooter(); }catch(e){toast(e.message);} };
    if($('#gSave')) $('#gSave').onclick=()=>sv({persen_dp:$('#gDP').value,biaya_penanganan:$('#gFee').value,biaya_tambahan_flat:$('#gFlat').value,biaya_verifikasi:$('#gVer').value});
    if($('#fSave')) $('#fSave').onclick=()=>{ const o={}; box.querySelectorAll('input[type=checkbox]').forEach(c=>o[c.dataset.k]=c.checked?'1':'0'); sv(o); };
    if($('#fkSave')) $('#fkSave').onclick=()=>sv({footer_tagline:$('#fTag').value,footer_email:$('#fMail').value,footer_wa:$('#fWa').value,footer_alamat:$('#fAddr').value,footer_copy:$('#fCopy').value},true);
  };
  $('#tabsA').querySelectorAll('button').forEach(b=>b.onclick=()=>show(b.dataset.t)); show('fin');
};

/* ---- upload langsung browser -> Cloudinary (bucket publik/privat) ---- */
async function uploadCloud(file, visibility='public', purpose=''){
  if(file.size>8*1024*1024) throw new Error('Maksimal 8 MB');
  const sig = await api('media-signature',{method:'POST',body:{visibility,purpose}});
  const fd = new FormData();
  fd.append('file',file); fd.append('api_key',sig.api_key); fd.append('timestamp',sig.timestamp);
  fd.append('signature',sig.signature); fd.append('folder',sig.folder); fd.append('tags','agrid');
  const r = await fetch(sig.endpoint,{method:'POST',body:fd});
  const j = await r.json(); if(!j.public_id) throw new Error((j.error&&j.error.message)||'Upload ditolak');
  return j.public_id;
}

/* ---- helper tabel ---- */
function tbl(heads,rows){ if(!rows||!rows.length) return null;
  return `<div class="tw"><table><thead><tr>${heads.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c??''}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`; }
