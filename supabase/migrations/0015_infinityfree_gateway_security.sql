-- Route account/session operations and seller listing writes through narrow
-- SECURITY DEFINER RPCs. The public anon key must never read password hashes
-- or session tokens directly.

CREATE OR REPLACE FUNCTION public.agr_register(p_email text, p_username text, p_password_hash text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE u public.users%ROWTYPE;
BEGIN
  IF p_email IS NULL OR length(p_email)>254 OR p_email !~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$' THEN
    RAISE EXCEPTION 'Email tidak valid' USING ERRCODE='22023';
  END IF;
  IF p_username IS NULL OR p_username !~ '^[a-z0-9_.-]{3,32}$' THEN
    RAISE EXCEPTION 'Nama pengguna tidak valid' USING ERRCODE='22023';
  END IF;
  IF p_password_hash IS NULL OR p_password_hash !~ '^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$' THEN
    RAISE EXCEPTION 'Hash password tidak valid' USING ERRCODE='22023';
  END IF;
  INSERT INTO public.users(email,username,nama,password_hash,role,roles,tipe,tipe_pembeli,created_at)
  VALUES(lower(btrim(p_email)),lower(btrim(p_username)),lower(btrim(p_username)),p_password_hash,'pembeli',
    '["pembeli"]'::jsonb,'Perorangan','Perorangan',now()) RETURNING * INTO u;
  RETURN jsonb_build_object('user',to_jsonb(u)-'password_hash');
EXCEPTION WHEN unique_violation THEN
  RAISE EXCEPTION 'Email atau nama pengguna sudah terdaftar' USING ERRCODE='23505';
END; $$;

CREATE OR REPLACE FUNCTION public.agr_login(p_identifier text,p_password text,p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE u public.users%ROWTYPE; active text;
BEGIN
  IF p_token IS NULL OR p_token !~ '^[a-f0-9]{64}$' OR p_password IS NULL THEN
    RAISE EXCEPTION 'Email/password salah' USING ERRCODE='42501';
  END IF;
  SELECT * INTO u FROM public.users WHERE lower(email)=lower(btrim(p_identifier)) OR lower(username)=lower(btrim(p_identifier)) LIMIT 1;
  IF NOT FOUND OR crypt(p_password,replace(u.password_hash,'$2y$','$2a$'))
      IS DISTINCT FROM replace(u.password_hash,'$2y$','$2a$') THEN
    RAISE EXCEPTION 'Email/password salah' USING ERRCODE='42501';
  END IF;
  active:=u.role;
  INSERT INTO public.sessions(user_id,token,active_role,expires_at)
  VALUES(u.id,p_token,active,now()+interval '7 days');
  RETURN jsonb_build_object('user',(to_jsonb(u)-'password_hash')||jsonb_build_object('role',active));
END; $$;

CREATE OR REPLACE FUNCTION public.agr_session_read(p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE u public.users%ROWTYPE; active text; user_data jsonb;
BEGIN
  SELECT public.users.* INTO u
  FROM public.sessions JOIN public.users ON users.id=sessions.user_id
  WHERE sessions.token=p_token AND sessions.expires_at>now();
  IF NOT FOUND THEN RAISE EXCEPTION 'Sesi tidak valid atau sudah kedaluwarsa' USING ERRCODE='42501'; END IF;
  SELECT active_role INTO active FROM public.sessions WHERE token=p_token AND expires_at>now();
  IF active IS NULL OR (active<>'admin' AND NOT (COALESCE(u.roles,'[]'::jsonb) ? active)) THEN active:=u.role; END IF;
  user_data:=(to_jsonb(u)-'password_hash')||jsonb_build_object('role',active);
  RETURN jsonb_build_object('user',user_data);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_logout(p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
  DELETE FROM public.sessions WHERE token=p_token;
  RETURN jsonb_build_object('ok',true);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_password_change(p_token text,p_old_password text,p_new_password_hash text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; old_hash text;
BEGIN
  SELECT users.id,users.password_hash INTO uid,old_hash FROM public.sessions JOIN public.users ON users.id=sessions.user_id
  WHERE sessions.token=p_token AND sessions.expires_at>now() FOR UPDATE OF users;
  IF uid IS NULL THEN RAISE EXCEPTION 'Sesi tidak valid' USING ERRCODE='42501'; END IF;
  IF crypt(p_old_password,replace(old_hash,'$2y$','$2a$')) IS DISTINCT FROM replace(old_hash,'$2y$','$2a$') THEN
    RAISE EXCEPTION 'Password lama salah' USING ERRCODE='42501';
  END IF;
  IF p_new_password_hash IS NULL OR p_new_password_hash !~ '^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$'
      OR crypt(p_old_password,replace(p_new_password_hash,'$2y$','$2a$'))
        IS NOT DISTINCT FROM replace(p_new_password_hash,'$2y$','$2a$') THEN
    RAISE EXCEPTION 'Password baru tidak valid atau sama dengan password lama' USING ERRCODE='22023';
  END IF;
  UPDATE public.users SET password_hash=p_new_password_hash WHERE id=uid;
  DELETE FROM public.sessions WHERE user_id=uid AND token<>p_token;
  RETURN jsonb_build_object('ok',true);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_product_update(p_token text,p_product_id bigint,p_payload jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; p public.products%ROWTYPE; stock_value integer; qmin integer; qmax integer;
BEGIN
  SELECT users.id,sessions.active_role INTO uid,active FROM public.sessions JOIN public.users ON users.id=sessions.user_id
  WHERE sessions.token=p_token AND sessions.expires_at>now() AND users.roles ? 'penjual';
  IF uid IS NULL OR active<>'penjual' THEN RAISE EXCEPTION 'Mode penjual diperlukan' USING ERRCODE='42501'; END IF;
  SELECT * INTO p FROM public.products WHERE id=p_product_id AND user_id=uid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Produk tidak ditemukan atau bukan milik Anda' USING ERRCODE='42501'; END IF;
  IF p_payload ? 'nama_product' AND btrim(p_payload->>'nama_product')='' THEN RAISE EXCEPTION 'Nama produk wajib diisi' USING ERRCODE='22023'; END IF;
  IF p_payload ? 'kategori' AND p_payload->>'kategori' NOT IN ('Pertanian','Perkebunan','Perikanan','Peternakan') THEN RAISE EXCEPTION 'Kategori tidak valid' USING ERRCODE='22023'; END IF;
  IF p_payload ? 'harga' AND COALESCE((p_payload->>'harga')::numeric,0)<=0 THEN RAISE EXCEPTION 'Harga harus lebih dari nol' USING ERRCODE='22023'; END IF;
  stock_value:=COALESCE(NULLIF(p_payload->>'stok','')::integer,p.stok);
  qmin:=COALESCE(NULLIF(p_payload->>'kuota_minimum','')::integer,p.kuota_minimum,1);
  qmax:=COALESCE(NULLIF(p_payload->>'kuota_maksimum','')::integer,p.kuota_maksimum);
  IF stock_value<0 OR qmin<1 OR (stock_value>0 AND qmin>stock_value) OR (qmax IS NOT NULL AND (qmax<qmin OR qmax>stock_value)) THEN
    RAISE EXCEPTION 'Stok dan kuota minimum/maksimum tidak valid' USING ERRCODE='22023';
  END IF;
  UPDATE public.products SET
    nama_product=COALESCE(p_payload->>'nama_product',nama_product),jenis=COALESCE(p_payload->>'jenis',jenis),
    kategori=COALESCE(p_payload->>'kategori',kategori),sub_kategori=COALESCE(p_payload->>'sub_kategori',sub_kategori),
    deskripsi=COALESCE(p_payload->>'deskripsi',deskripsi),harga=COALESCE(NULLIF(p_payload->>'harga','')::numeric,harga),
    satuan=COALESCE(p_payload->>'satuan',satuan),stok=stock_value,foto=COALESCE(p_payload->>'foto',foto),
    lat=COALESCE(NULLIF(p_payload->>'lat','')::double precision,lat),lng=COALESCE(NULLIF(p_payload->>'lng','')::double precision,lng),
    alamat_lahan=COALESCE(p_payload->>'alamat_lahan',alamat_lahan),kuota_minimum=qmin,kuota_maksimum=qmax,
    status=CASE WHEN p_payload->>'status' IN ('aktif','nonaktif') THEN p_payload->>'status' ELSE status END,updated_at=now()
  WHERE id=p.id RETURNING * INTO p;
  RETURN to_jsonb(p);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_product_delete(p_token text,p_product_id bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text;
BEGIN
  SELECT users.id,sessions.active_role INTO uid,active FROM public.sessions JOIN public.users ON users.id=sessions.user_id
  WHERE sessions.token=p_token AND sessions.expires_at>now() AND users.roles ? 'penjual';
  IF uid IS NULL OR active<>'penjual' THEN RAISE EXCEPTION 'Mode penjual diperlukan' USING ERRCODE='42501'; END IF;
  IF EXISTS(SELECT 1 FROM public.bookings WHERE product_id=p_product_id) THEN
    RAISE EXCEPTION 'Produk sudah memiliki pesanan; ubah status menjadi nonaktif' USING ERRCODE='23503';
  END IF;
  DELETE FROM public.products WHERE id=p_product_id AND user_id=uid;
  IF NOT FOUND THEN RAISE EXCEPTION 'Produk tidak ditemukan atau bukan milik Anda' USING ERRCODE='42501'; END IF;
  RETURN jsonb_build_object('ok',true);
END; $$;

-- Remove broad table grants and policies that exposed account credentials and
-- reusable session tokens to every anonymous visitor.
DROP POLICY IF EXISTS users_public_login ON public.users;
DROP POLICY IF EXISTS users_public_insert ON public.users;
DROP POLICY IF EXISTS users_public_profile ON public.users;
DROP POLICY IF EXISTS sessions_anon_all ON public.sessions;
DROP POLICY IF EXISTS users_public_profile_safe ON public.users;
CREATE POLICY users_public_profile_safe ON public.users FOR SELECT TO anon,authenticated
  USING (role IN ('penjual','pembeli') AND roles ? 'penjual');
REVOKE ALL ON TABLE public.users,public.sessions FROM anon,authenticated;
GRANT SELECT (id,nama,role,roles,tipe,tipe_penjual,tipe_pembeli,alamat,lat,lng,avatar_url,logo_url)
  ON public.users TO anon,authenticated;

REVOKE ALL ON FUNCTION public.agr_register(text,text,text),public.agr_login(text,text,text),
  public.agr_session_read(text),public.agr_logout(text),public.agr_password_change(text,text,text),
  public.agr_product_update(text,bigint,jsonb),public.agr_product_delete(text,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agr_register(text,text,text),public.agr_login(text,text,text),
  public.agr_session_read(text),public.agr_logout(text),public.agr_password_change(text,text,text),
  public.agr_product_update(text,bigint,jsonb),public.agr_product_delete(text,bigint) TO anon,authenticated;
