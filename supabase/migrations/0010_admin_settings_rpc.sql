-- Admin setting writes must go through a database function because the
-- InfinityFree gateway uses the Supabase anon key and pengaturan has no
-- direct write policy. The function revalidates the signed-in admin session.
CREATE OR REPLACE FUNCTION public.agr_admin_settings_save(
  p_token text,
  p_settings jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_active_role text;
  v_user_role text;
  v_roles jsonb;
  v_allowed_keys text[] := ARRAY[
    'persen_dp', 'biaya_penanganan', 'biaya_tambahan_flat', 'biaya_verifikasi',
    'beranda_aktif', 'fitur_marketplace', 'fitur_booking_dp', 'fitur_payment_gateway',
    'fitur_eviden_gps', 'fitur_rating', 'fitur_favorit', 'fitur_chat_ai',
    'fitur_crypto', 'fitur_storage_cloud',
    'footer_tagline', 'footer_email', 'footer_wa', 'footer_alamat', 'footer_copy'
  ];
  v_entry record;
  v_saved jsonb := '{}'::jsonb;
BEGIN
  SELECT COALESCE(s.active_role, u.role), u.role, u.roles
    INTO v_active_role, v_user_role, v_roles
  FROM public.sessions AS s
  JOIN public.users AS u ON u.id = s.user_id
  WHERE s.token = p_token AND s.expires_at > now();

  IF v_active_role IS DISTINCT FROM 'admin'
     OR (v_user_role <> 'admin' AND NOT (COALESCE(v_roles, '[]'::jsonb) ? 'admin')) THEN
    RAISE EXCEPTION 'Sesi admin tidak valid atau kedaluwarsa' USING ERRCODE = '42501';
  END IF;

  IF jsonb_typeof(p_settings) <> 'object'
     OR p_settings = '{}'::jsonb
     OR (SELECT count(*) FROM jsonb_object_keys(p_settings)) > 20 THEN
    RAISE EXCEPTION 'Format pengaturan tidak valid' USING ERRCODE = '22023';
  END IF;

  FOR v_entry IN SELECT key, value FROM jsonb_each(p_settings)
  LOOP
    IF NOT (v_entry.key = ANY(v_allowed_keys))
       OR jsonb_typeof(v_entry.value) NOT IN ('string', 'number', 'boolean')
       OR length(v_entry.value #>> '{}') > 2000 THEN
      RAISE EXCEPTION 'Kunci atau nilai pengaturan tidak diizinkan' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.pengaturan(key, value)
    VALUES (v_entry.key, v_entry.value #>> '{}')
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

    v_saved := v_saved || jsonb_build_object(v_entry.key, v_entry.value #>> '{}');
  END LOOP;

  RETURN v_saved;
END;
$$;

REVOKE ALL ON FUNCTION public.agr_admin_settings_save(text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agr_admin_settings_save(text, jsonb) TO anon, authenticated, service_role;
