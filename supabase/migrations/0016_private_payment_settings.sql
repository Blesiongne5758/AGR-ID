-- Seller bank/QRIS instructions are private: expose only to the owning seller
-- through a token-scoped RPC. Admin reads all settings through a separate RPC.

CREATE OR REPLACE FUNCTION public.agr_seller_payment_settings_get(p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE uid bigint; active text; raw_value text; result jsonb;
BEGIN
  SELECT sessions.user_id,sessions.active_role INTO uid,active
  FROM public.sessions JOIN public.users ON users.id=sessions.user_id
  WHERE sessions.token=p_token AND sessions.expires_at>now() AND users.roles ? 'penjual';
  IF uid IS NULL OR active<>'penjual' THEN RAISE EXCEPTION 'Mode penjual diperlukan' USING ERRCODE='42501'; END IF;
  SELECT value INTO raw_value FROM public.pengaturan WHERE key='pembayaran_penjual_'||uid::text;
  BEGIN result:=raw_value::jsonb; EXCEPTION WHEN OTHERS THEN result:='{}'::jsonb; END;
  RETURN jsonb_build_object('metode_dp',COALESCE(result->'metode_dp','["Transfer Bank"]'::jsonb),
    'rekening',COALESCE(result->>'rekening',''),'qris',COALESCE(result->>'qris',''),
    'tujuan_tunai',COALESCE(result->>'tujuan_tunai',''));
END; $$;

CREATE OR REPLACE FUNCTION public.agr_admin_settings_list(p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE active text; result jsonb;
BEGIN
  SELECT sessions.active_role INTO active FROM public.sessions JOIN public.users ON users.id=sessions.user_id
  WHERE sessions.token=p_token AND sessions.expires_at>now();
  IF active IS DISTINCT FROM 'admin' THEN RAISE EXCEPTION 'Akses admin diperlukan' USING ERRCODE='42501'; END IF;
  SELECT COALESCE(jsonb_agg(jsonb_build_object('key',key,'value',value) ORDER BY key),'[]'::jsonb)
  INTO result FROM public.pengaturan;
  RETURN result;
END; $$;

DROP POLICY IF EXISTS pengaturan_public_read ON public.pengaturan;
CREATE POLICY pengaturan_public_read ON public.pengaturan FOR SELECT TO anon,authenticated USING (
  key IN ('footer_tagline','footer_email','footer_wa','footer_alamat','footer_copy','ticker_harian','beranda_aktif',
    'fitur_pembayaran','fitur_booking_dp','fitur_biaya','persen_dp','biaya_penanganan','biaya_tambahan_flat')
);

REVOKE ALL ON FUNCTION public.agr_seller_payment_settings_get(text),public.agr_admin_settings_list(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agr_seller_payment_settings_get(text),public.agr_admin_settings_list(text) TO anon,authenticated;
