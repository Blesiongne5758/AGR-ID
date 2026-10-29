/* =====================================================================
   AGR.BIZ.ID — Frontend SPA statis (InfinityFree htdocs)
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

const routes = { '#/beranda':'home', '#/marketplace':'market', '#/login':'login', '#/daftar':'register', '#/chat':'chat', '#/pesan':'productChats', '#/akun':'akun',
  '#/dashboard':'dash', '#/dashboard/penjual':'dashPenjual', '#/dashboard/pembeli':'dashPembeli', '#/dashboard/admin':'dashAdmin',
  '#/produk-baru':'formProduk' };
function resolve(){
  updateMobileNav();
  if(window._productChatTimer){ clearInterval(window._productChatTimer); window._productChatTimer=null; }
  const raw = location.hash.split('?')[0];
  const chatMatch = raw.match(/^#\/pesan\/(\d+)$/);
  if(chatMatch){ if(!S.token){location.hash='#/login';return;} renderers.productChat(+chatMatch[1]); return; }
  const md = raw.match(/^#\/produk\/(\d+)$/);
  if(md){ tampilDetail(md[1]); return; }
  const key = Object.keys(routes).sort((a,b)=>b.length-a.length).find(k => raw.startsWith(k)) ?? '';
  const view = key ? routes[key] : 'home';
  const qs = new URLSearchParams(location.hash.split('?')[1]||'');
  const prot = ['dash','dashPenjual','dashPembeli','dashAdmin','formProduk','productChats'];
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
  const roles=Array.isArray(u?.roles)?u.roles:(u?[u.role]:[]);
  const modeControl=!u||u.role==='admin'?'':(roles.includes('penjual')
    ? `<button class="btn btn-outline" id="btnSwitchRole" data-role="${u.role==='penjual'?'pembeli':'penjual'}">Mode ${u.role==='penjual'?'Pembeli':'Penjual'}</button>`
    : `<a class="btn btn-outline" href="#/akun">Aktifkan Mode Penjual</a>`);
  $('#navAuth').innerHTML = u
    ? `<a class="btn btn-ghost" href="#/dashboard/${u.role}">Dashboard</a>${modeControl}<a class="btn btn-ghost" href="#/akun" title="Pengaturan pengguna">⚙️ Akun</a><button class="btn btn-outline" id="btnLogout"><span aria-hidden="true">↪</span> Keluar</button>`
    : `<a class="btn btn-ghost" href="#/login">Masuk</a><a class="btn btn-primary" href="#/daftar">Daftar</a>`;
  const bs=$('#btnSwitchRole'); if(bs) bs.onclick=async()=>{try{const r=await api('switch-role',{method:'POST',body:{role:bs.dataset.role}});S.user=r.user;updateNav();toast('Mode akun beralih ke '+r.user.role+'.');location.hash='#/dashboard/'+r.user.role;}catch(e){toast(e.message);if(/lengkapi informasi/i.test(e.message))location.hash='#/akun';} };
  const bl=$('#btnLogout'); if(bl) bl.onclick=async()=>{ try{await api('logout',{method:'POST'})}catch(e){} S.token='';S.user=null;updateNav();location.hash='#/beranda'; };
  updateMobileNav();
}

function updateMobileNav(){
  const nav=$('#mobileBottomNav'); if(!nav)return;
  const u=S.user, hash=(location.hash||'#/beranda').split('?')[0];
  const links={home:'#/beranda',search:'#/marketplace',messages:u?'#/pesan':'#/login',profile:u?'#/akun':'#/login',add:u?.role==='penjual'?'#/produk-baru':u?.role==='admin'?'#/dashboard/admin':u?'#/dashboard/pembeli':'#/daftar'};
  nav.querySelectorAll('[data-nav]').forEach(item=>{
    const key=item.dataset.nav; item.href=links[key]||'#/beranda';
    const active=(key==='home'&&hash==='#/beranda')||(key==='search'&&hash.startsWith('#/marketplace'))||(key==='messages'&&hash.startsWith('#/pesan'))||(key==='profile'&&['#/akun','#/dashboard','#/dashboard/pembeli','#/dashboard/penjual','#/dashboard/admin'].includes(hash))||(key==='add'&&hash==='#/produk-baru');
    item.classList.toggle('is-active',active);
    if(active)item.setAttribute('aria-current','page');else item.removeAttribute('aria-current');
    if(key==='add')item.setAttribute('aria-label',u?.role==='penjual'?'Tambah produk jualan':u?.role==='pembeli'?'Buka daftar belanja':'Buat akun');
  });
}

/* ==================== VIEWS ==================== */
const renderers = {};

renderers.home = async () => {
  let prods=[]; try{ prods = await api('products',{qs:'limit=8'}); }catch(e){}
  $('#app').innerHTML = `
  <section class="hero">
    <h1>AGR.BIZ.ID</h1><p class="brand-tagline">Agrikultur Bisnis Indonesia</p><h2>Marketplace Pertanian, Perkebunan, Perikanan &amp; Peternakan</h2>
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
          <button class="btn btn-outline" id="btnFav">${fav?'★':'☆'} Favorit</button>
          ${+S.user.id!==+p.user_id?'<button class="btn btn-outline" id="btnProductChat">Tanya Penjual</button>':''}`:!S.user?`<a class="btn btn-primary" href="#/login">Masuk untuk Menawar atau Bertanya</a>`:'<span class="muted">Hanya pembeli yang dapat menawar dan memulai chat produk.</span>'}
      </div>
      <div id="offerBox"></div>
    </div></div>`;
  const bf=$('#btnFav'); if(bf) bf.onclick=async()=>{ try{ const r=await api('favorite-toggle',{method:'POST',body:{target_type:'produk',target_id:+id}}); bf.innerHTML=(r.favorit?'★':'☆')+' Favorit'; toast(r.favorit?'Ditambahkan ke favorit':'Dihapus dari favorit'); }catch(e){toast(e.message);} };
  const bc=$('#btnProductChat'); if(bc) bc.onclick=async()=>{try{const c=await api('chat-start',{method:'POST',body:{product_id:+id}});location.hash='#/pesan/'+c.id;}catch(e){toast(e.message);}};
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
  $('#app').innerHTML = `<div class="auth card-form"><h2>Masuk ke AGR.BIZ.ID</h2>
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
  $('#app').innerHTML = `<div class="auth card-form"><h2>Pendaftaran AGR.BIZ.ID</h2><p class="muted small">Daftar sebagai pembeli dengan tiga data dasar. Lengkapi profil pengguna dan usaha di Pengaturan Pengguna jika ingin mengaktifkan mode Penjual.</p>
    <label>Email<input id="re" class="input" type="email" autocomplete="email"></label>
    <label>Nama Pengguna<input id="run" class="input" type="text" minlength="3" maxlength="32" pattern="[a-zA-Z0-9_.-]{3,32}" autocomplete="username" placeholder="contoh: tani_makmur"></label>
    <div class="rel"><label>Kata Sandi (min. 8 karakter)<input id="rpw" class="input" type="password" name="password" autocomplete="new-password"></label>
      <button type="button" class="btn btn-outline btn-sm pwd-eye" data-for="rpw" title="Tampilkan/sembunyikan">👁</button></div>
    <div class="pw-meter"><i id="pwBar"></i></div><small id="pwHint" class="muted">Gunakan generator: <button type="button" class="btn btn-outline btn-sm" id="pwGen">🔐 Buat Password Kuat</button></small>
    <button class="btn btn-primary wide" id="rgo">Daftar</button>
    <p class="muted center">Sudah punya akun? <a href="#/login">Masuk</a></p></div>`;
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

  $('#rgo').onclick=async()=>{
    const pw=$('#rpw').value;
    if(pw.length<8||pwScore(pw)<3){ toast('Password terlalu lemah — minimal 8 karakter dengan huruf besar, angka & simbol (pakai generator 🔐)'); $('#rpw').focus(); return; }
    const email=$('#re').value.trim(), username=$('#run').value.trim().toLowerCase();
    if(!/^[a-z0-9_.-]{3,32}$/.test(username)){toast('Nama pengguna harus 3–32 karakter dan hanya memakai huruf, angka, titik, _ atau -');$('#run').focus();return;}
    try{ const r=await api('register',{method:'POST',body:{email,password:pw,username}});
      toast('Akun berhasil dibuat. Silakan masuk.'); location.hash='#/login';
    }catch(e){ toast(e.message); } };
};

/* ---- Pengaturan profil, mode akun dan kata sandi ---- */
renderers.akun = async () => {
  if(!S.user){ location.hash='#/login'; return; }
  const u=S.user, roles=Array.isArray(u.roles)?u.roles:[u.role];
  const bank=await api('seller-payment-settings').catch(()=>({metode_dp:['Transfer Bank'],rekening:'',qris:'',tujuan_tunai:''}));
  const sellerTypes=['Perorangan','Kelompok/Paguyuban','Koperasi','Perusahaan'];
  const missing=[];
  if(!u.nama||u.nama===u.username)missing.push('nama lengkap/nama usaha');
  if(!u.no_hp)missing.push('nomor telepon'); if(!u.alamat)missing.push('alamat lengkap');
  if(!u.kota)missing.push('kota/kabupaten'); if(!u.provinsi)missing.push('provinsi');
  if(u.lat==null||u.lng==null)missing.push('koordinat lokasi (GPS)');
  if(!sellerTypes.includes(u.tipe_penjual))missing.push('tipe penjual');
  if(u.tipe_penjual&&u.tipe_penjual!=='Perorangan'){if(!u.npwp)missing.push('NPWP');if(!u.nib)missing.push('NIB');}
  $('#app').innerHTML = `<section class="auth card-form account-settings-card"><h2>Pengaturan Pengguna</h2>
    <p class="muted small account-summary">${esc(u.nama||u.username)} · ${esc(u.email)} · @${esc(u.username||'')}</p>
    <div class="user-action-tabs settings-menu" id="settingsMenu" role="tablist" aria-label="Menu pengaturan">
      <button class="on" data-panel="profile" role="tab" aria-selected="true">Ubah Data Profil</button><button data-panel="bank" role="tab" aria-selected="false">Data Bank</button><button data-panel="password" role="tab" aria-selected="false">Ganti Password</button><button data-panel="seller" role="tab" aria-selected="false">Mode Penjual</button>
    </div>
    <section class="settings-panel" id="settings-profile"><h3>Data Profil &amp; Usaha</h3><p class="muted small">Lengkapi profil sebelum mengaktifkan mode Penjual.</p>
      <label>Nama Lengkap / Nama Usaha<input id="pNama" class="input" value="${esc(u.nama||'')}" autocomplete="name"></label>
      <label>Nomor Telepon / WhatsApp<input id="pPhone" class="input" value="${esc(u.no_hp||'')}" autocomplete="tel"></label>
      <label>Alamat Lengkap<textarea id="pAlamat" class="input" rows="2" autocomplete="street-address">${esc(u.alamat||'')}</textarea></label>
      <div class="grid2"><label>Kota/Kabupaten<input id="pKota" class="input" value="${esc(u.kota||'')}"></label><label>Provinsi<input id="pProvinsi" class="input" value="${esc(u.provinsi||'')}"></label></div>
      <label>Tipe Penjual<select id="pTipe" class="input"><option value="">Pilih tipe penjual</option>${sellerTypes.map(t=>`<option ${u.tipe_penjual===t?'selected':''}>${t}</option>`).join('')}</select></label>
      <div id="pOrgFields"><label>NPWP Usaha / Organisasi<input id="pNpwp" class="input" value="${esc(u.npwp||'')}"></label><label>NIB Usaha / Organisasi<input id="pNib" class="input" value="${esc(u.nib||'')}"></label><small class="muted">Wajib untuk Kelompok/Paguyuban, Koperasi, atau Perusahaan.</small></div>
      <div class="grid2"><label>Latitude<input id="pLat" class="input" type="number" step="0.000001" value="${u.lat??''}"></label><label>Longitude<input id="pLng" class="input" type="number" step="0.000001" value="${u.lng??''}"></label></div>
      <button class="btn btn-outline" id="pGps">📍 Isi lokasi dari GPS</button><button class="btn btn-primary wide" id="pSave">Simpan Profil</button>
    </section>
    <section class="settings-panel" id="settings-bank" hidden><h3>Data Pembayaran / Bank</h3><p class="muted small">Atur informasi pembayaran yang ditampilkan kepada pembeli.</p>
      <label>Metode Pembayaran</label><div class="settings-methods">${['Transfer Bank','QRIS','Tunai'].map(m=>`<label class="settings-method"><input type="checkbox" name="payMethod" value="${m}" ${(bank.metode_dp||[]).includes(m)?'checked':''}> ${m}</label>`).join('')}</div>
      <label>Nama bank, nomor rekening, dan nama pemilik<input id="bankAccount" class="input" maxlength="160" value="${esc(bank.rekening||'')}" placeholder="Bank ABC · 1234567890 · Nama Pemilik"></label>
      <label>Informasi QRIS (opsional)<input id="bankQris" class="input" maxlength="500" value="${esc(bank.qris||'')}" placeholder="URL gambar QRIS atau petunjuk pembayaran"></label>
      <label>Petunjuk tunai (opsional)<textarea id="bankCash" class="input" rows="2" maxlength="300">${esc(bank.tujuan_tunai||'')}</textarea></label>
      <button class="btn btn-primary wide" id="bankSave">Simpan Data Bank</button>
    </section>
    <section class="settings-panel" id="settings-password" hidden><h3>Keamanan Akun</h3><label>Password Lama<input id="kOld" class="input" type="password" autocomplete="current-password"></label>
      <label>Password Baru (min. 8 karakter)<input id="kNew" class="input" type="password" autocomplete="new-password"></label><div class="pw-meter"><i id="kBar"></i></div>
      <label>Konfirmasi Password Baru<input id="kNew2" class="input" type="password" autocomplete="new-password"></label><button class="btn btn-primary wide" id="kSave">Simpan Password</button>
    </section>
    <section class="settings-panel" id="settings-seller" hidden><h3>Mode Penjual</h3>${u.role==='penjual'?'<p class="panel">Mode Penjual sedang aktif.</p><button class="btn btn-outline wide" id="pBuyerMode">Beralih ke Mode Pembeli</button>':u.role==='admin'?'<p class="panel">Mode penjual tidak tersedia untuk admin.</p>':`<p class="muted small">${missing.length?'Lengkapi: '+esc(missing.join(', '))+'.':'Profil tampak lengkap. Simpan profil sebelum mengaktifkan mode.'}</p><button class="btn btn-primary wide" id="pSellerMode" ${missing.length?'disabled':''}>Aktifkan Mode Penjual</button>`}</section>
    </section>`;
  $('#settingsMenu').querySelectorAll('button').forEach(b=>b.onclick=()=>{
    $('#settingsMenu').querySelectorAll('button').forEach(x=>{const active=x===b;x.classList.toggle('on',active);x.setAttribute('aria-selected',String(active));});
    document.querySelectorAll('.settings-panel').forEach(p=>p.hidden=p.id!=='settings-'+b.dataset.panel);
    history.replaceState(null,'','#/akun?tab='+b.dataset.panel);
  });
  const initialTab=new URLSearchParams(location.hash.split('?')[1]||'').get('tab');
  const initialBtn=$(`#settingsMenu [data-panel="${initialTab}"]`); if(initialBtn)initialBtn.click();
  const profileData=()=>({nama:$('#pNama').value,no_hp:$('#pPhone').value,alamat:$('#pAlamat').value,kota:$('#pKota').value,provinsi:$('#pProvinsi').value,tipe_penjual:$('#pTipe').value,npwp:$('#pNpwp').value,nib:$('#pNib').value,lat:$('#pLat').value||null,lng:$('#pLng').value||null});
  const toggleOrg=()=>$('#pOrgFields').style.display=$('#pTipe').value&&$('#pTipe').value!=='Perorangan'?'':'none';
  $('#pTipe').onchange=toggleOrg;toggleOrg();
  $('#pGps').onclick=()=>{if(!navigator.geolocation){toast('Browser tidak mendukung geolokasi');return;}navigator.geolocation.getCurrentPosition(pos=>{$('#pLat').value=pos.coords.latitude.toFixed(6);$('#pLng').value=pos.coords.longitude.toFixed(6);},()=>toast('Izin lokasi tidak tersedia'));};
  $('#pSave').onclick=async()=>{try{const r=await api('update-profile',{method:'POST',body:profileData()});S.user=r.user;updateNav();toast('Profil berhasil disimpan');renderers.akun();}catch(e){toast(e.message);}};
  $('#bankSave').onclick=async()=>{try{const metode_dp=[...document.querySelectorAll('[name="payMethod"]:checked')].map(x=>x.value);await api('seller-payment-settings',{method:'POST',body:{metode_dp,rekening:$('#bankAccount').value,qris:$('#bankQris').value,tujuan_tunai:$('#bankCash').value}});toast('Data pembayaran berhasil disimpan');}catch(e){toast(e.message);}};
  const activate=async(target)=>{try{const saved=await api('update-profile',{method:'POST',body:profileData()});S.user=saved.user;const r=await api('switch-role',{method:'POST',body:{role:target}});S.user=r.user;updateNav();toast(target==='penjual'?'Mode Penjual aktif':'Mode Pembeli aktif');location.hash='#/dashboard/'+target;}catch(e){toast(e.message);}};
  const pSeller=$('#pSellerMode');if(pSeller)pSeller.onclick=()=>activate('penjual');
  const pBuyer=$('#pBuyerMode');if(pBuyer)pBuyer.onclick=()=>activate('pembeli');
  const score=v=>{ let s=0; if(v.length>=8)s++; if(/[a-z]/.test(v)&&/[A-Z]/.test(v))s++; if(/\d/.test(v))s++; if(/[^A-Za-z0-9]/.test(v))s++; if(v.length>=12)s++; return Math.min(s,5); };
  $('#kNew').oninput=()=>{ const v=$('#kNew').value,s=score(v); $('#kBar').style.width=(s*20)+'%'; $('#kBar').className='lvl'+s; };
  $('#kSave').onclick=async()=>{
    if($('#kNew').value!==$('#kNew2').value){ toast('Konfirmasi password tidak sama'); return; }
    if(score($('#kNew').value)<3){ toast('Password baru terlalu lemah — tambahkan huruf besar/angka/simbol'); return; }
    try{ await api('change-password',{method:'POST',body:{old_password:$('#kOld').value,new_password:$('#kNew').value}});
      toast('Password berhasil diganti'); $('#kOld').value=$('#kNew').value=$('#kNew2').value=''; }catch(e){toast(e.message);} };
};

renderers.chat = () => {
  $('#app').innerHTML = `<div class="chatbox card"><h2>🤖 AI Assistant AGR.BIZ.ID</h2><div id="msgs" class="msgs"></div>
    <div class="chat-in"><input id="cin" class="input" placeholder="Tanya: cara posting cabai merah, cari produk ikan air tawar…"><button class="btn btn-primary" id="csnd">Kirim</button></div>
    <p class="muted small">Mode aturan lokal aktif. Untuk jawaban LLM penuh, hubungkan backend Flask via config.php (AGR_ID_API_URL).</p></div>`;
  msg('Halo! Saya asisten AGR.BIZ.ID. Saya bisa membantu mengisi informasi produk atau mencari produk yang Anda butuhkan. Coba: “cara jual cabai” atau “cari ikan nila”.');
  const send=()=>{ const v=$('#cin').value.trim(); if(!v)return; msg(v,'me'); $('#cin').value=''; botJawab(v); };
  $('#csnd').onclick=send; $('#cin').onkeydown=e=>e.key==='Enter'&&send();
};

renderers.productChats = async () => {
  if(!S.token){location.hash='#/login';return;}
  let chats=[]; try{chats=await api('chats');}catch(e){$('#app').innerHTML=`<div class="panel"><h2>Pesan Produk</h2><p>${esc(e.message)}</p></div>`;return;}
  $('#app').innerHTML=`<section class="pc-wrap"><div class="pc-title"><div><h2>Pesan Produk</h2><p class="muted">Percakapan dengan pembeli atau pemilik listing.</p></div><a class="btn btn-outline" href="#/marketplace">Cari Produk</a></div>
    <div class="pc-notice"><b>Pengingat privasi</b><br>Para pengguna harap waspada dan hati-hati dalam menukar informasi yang bersifat Privasi agar tidak saling bertukar nomor kontak,alamat dan email atau informasi pibadi dan sensitif lainnya dan segala resiko yang disebebkan kelalaian para pengguna  diluar dari portal Agrid bukan menjadi tanggung jawab Portal Agrid. Terima Kasih</div>
    <div class="pc-list">${chats.map(c=>`<a class="pc-thread" href="#/pesan/${c.id}"><span class="pc-avatar">${esc((c.other_name||'?').slice(0,1).toUpperCase())}</span><span class="pc-thread-main"><b>${esc(c.product_name)}</b><small>${esc(c.other_name)} · ${esc(c.last_message||'Percakapan dimulai')}</small></span><small class="muted">${esc((c.updated_at||'').slice(0,16).replace('T',' '))}</small></a>`).join('')||'<div class="pc-empty">Belum ada percakapan. Buka listing produk dan pilih “Tanya Penjual”.</div>'}</div></section>`;
};

renderers.productChat = async (id) => {
  if(window._productChatTimer){clearInterval(window._productChatTimer);window._productChatTimer=null;}
  if(!S.token){location.hash='#/login';return;}
  let data;
  try{data=await api('chat-messages',{qs:'id='+id});}
  catch(e){$('#app').innerHTML=`<section class="pc-wrap"><a href="#/pesan">← Semua pesan</a><div class="panel"><p>${esc(e.message)}</p></div></section>`;return;}
  const c=data.conversation, other=+S.user.id===+c.buyer_id?(c.seller_name||'Penjual'):(c.buyer_name||'Pembeli');
  $('#app').innerHTML=`<section class="pc-wrap"><a href="#/pesan">← Semua pesan</a><div class="pc-title pc-title-chat"><div><h2>${esc(c.product_name)}</h2><p class="muted">${esc(other)} · ${rp(c.product_harga)}/${esc(c.product_satuan)}</p></div><a href="#/produk/${c.product_id}" class="btn btn-outline">Lihat Produk</a></div>
    <div class="pc-messages" id="pcMessages"></div><form class="pc-compose" id="pcCompose"><textarea id="pcBody" class="input" rows="2" maxlength="2000" placeholder="Tanyakan detail produk…" required></textarea><button class="btn btn-primary" type="submit">Kirim</button><small class="muted">Maksimal 2.000 karakter. Hindari membagikan informasi pribadi atau kontak.</small></form></section>`;
  const draw=async()=>{try{const fresh=await api('chat-messages',{qs:'id='+id});data=fresh;$('#pcMessages').innerHTML=(fresh.messages||[]).map(m=>m.is_system?`<div class="pc-system"><b>${esc(m.sender_name||'AGR.BIZ.ID')}</b><br>${esc(m.body)}</div>`:`<div class="pc-bubble ${+m.sender_id===+S.user.id?'mine':''}"><b>${+m.sender_id===+S.user.id?'Anda':esc(m.sender_name)}</b><div>${esc(m.body).replace(/\n/g,'<br>')}</div><small>${esc((m.created_at||'').slice(0,16).replace('T',' '))}</small></div>`).join('');$('#pcMessages').scrollTop=$('#pcMessages').scrollHeight;}catch(e){toast(e.message);}};
  $('#pcCompose').onsubmit=async e=>{e.preventDefault();const body=$('#pcBody').value.trim();if(!body)return;const submit=$('#pcCompose button');submit.disabled=true;try{await api('chat-send',{method:'POST',body:{conversation_id:+id,body}});$('#pcBody').value='';await draw();}catch(err){toast(err.message);}finally{submit.disabled=false;}};
  await draw(); window._productChatTimer=setInterval(()=>{if(location.hash.startsWith('#/pesan/'))draw();},7000);
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
   <div class="tabs user-action-tabs" id="tabsP" role="tablist" aria-label="Menu dashboard penjual"><button class="on" data-t="prod">Produk Saya</button><button data-t="ofr">Penawaran</button><button data-t="pln">Approval Pelunasan</button><button data-t="rpt">Laporan Penjualan</button></div>
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
   <div class="tabs user-action-tabs" id="tabsB" role="tablist" aria-label="Menu dashboard pembeli"><button class="on" data-t="ofr">Penawaran Saya</button><button data-t="trx">Transaksi & Pelunasan</button><button data-t="rpt">Laporan Pembelian</button><button data-t="fav">Favorit</button></div><div id="tabB"></div>`;
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
    if(f){ try{ foto=await uploadCloud(f,'public','product'); }catch(e){ toast('Foto gagal diupload: '+e.message); return; } }
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
  const allowed = visibility === 'private' && purpose === 'kyc'
    ? ['image/jpeg','image/png','image/webp','application/pdf']
    : ['image/jpeg','image/png','image/webp'];
  if(!allowed.includes(file.type)) throw new Error('Format file harus JPG, PNG, atau WebP'+(visibility === 'private' && purpose === 'kyc' ? ', atau PDF' : ''));
  const sig = await api('media-signature',{method:'POST',body:{visibility,purpose}});
  const fd = new FormData();
  fd.append('file',file); fd.append('api_key',sig.api_key); fd.append('signature',sig.signature);
  Object.entries(sig.upload_params||{timestamp:sig.timestamp,folder:sig.folder,tags:'agrid'}).forEach(([key,value])=>fd.append(key,String(value)));
  const r = await fetch(sig.endpoint,{method:'POST',body:fd});
  let j; try{j=await r.json();}catch(_){throw new Error('Respons Cloudinary tidak valid');}
  if(!r.ok||!j.public_id) throw new Error((j.error&&j.error.message)||'Upload ditolak');
  // Public photos use Cloudinary's CDN URL directly. Private KYC keeps only
  // its public_id so access still goes through the signed private URL route.
  return visibility === 'private' ? j.public_id : (j.secure_url || j.public_id);
}

/* ---- helper tabel ---- */
function tbl(heads,rows){ if(!rows||!rows.length) return null;
  return `<div class="tw"><table><thead><tr>${heads.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c??''}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`; }
