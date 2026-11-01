<?php
/**
 * AGR.BIZ.ID — contoh konfigurasi.
 * Salin file ini menjadi config.php lalu isi kredensial asli.
 * JANGAN commit config.php (sudah di-.gitignore).
 */
return [
    // ---- Supabase (Project Settings -> API) ----
    // Boleh URL lengkap ATAU ref project saja:
    //   'https://abcdefgh.supabase.co'  atau  'abcdefgh'
    'supabase_url'    => 'https://xxxxxxxx.supabase.co',
    // Gunakan Publishable key (sb_publishable_...) atau legacy anon public
    // key (JWT eyJ...). Jangan gunakan secret/service_role key.
    // sb_secret_ adalah service key SUPER-PRIVILEGED — jangan pernah
    // diletakkan di hosting publik/htdocs; hanya untuk backend privat (Flask).
    'supabase_key'    => '',

    // ---- Cloudinary (Dashboard -> Settings -> Access Keys) ----
    // API Secret hanya digunakan oleh api.php untuk membuat tanda tangan
    // upload sementara. Jangan pernah mengirim atau menaruhnya di JavaScript.
    // Upload foto publik memakai image/upload bertanda tangan; dokumen KYC
    // privat memakai auto/upload dalam folder per pengguna.
    'cloudinary_cloud'   => 'nama-cloud-anda',
    'cloudinary_key'     => '123456789012345',
    'cloudinary_secret'  => 'secret-16-karakter',

    // ---- Backend Flask opsional (Render/Railway/VPS) untuk payment gateway,
    //      blockchain/crypto & AI chat. Kosongkan bila tidak dipakai. ----
    'flask_url'       => '',                            // cth: https://agr-id-api.onrender.com
];

