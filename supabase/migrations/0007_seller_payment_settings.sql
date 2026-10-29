-- Seller payment instructions are stored in the shared settings table.
-- Writes must pass through this function because the PHP gateway uses anon key.
CREATE OR REPLACE FUNCTION public.agr_seller_payment_settings_save(
  p_token text,
  p_settings jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user_id bigint;
  v_active_role text;
  v_user_role text;
  v_roles jsonb;
  v_methods jsonb;
  v_settings jsonb;
BEGIN
  SELECT u.id, COALESCE(s.active_role, u.role), u.role, u.roles
    INTO v_user_id, v_active_role, v_user_role, v_roles
  FROM public.sessions s
  JOIN public.users u ON u.id = s.user_id
  WHERE s.token = p_token AND s.expires_at > now();

  IF v_user_id IS NULL
     OR v_active_role IS DISTINCT FROM 'penjual'
     OR (v_user_role <> 'penjual' AND NOT (COALESCE(v_roles, '[]'::jsonb) ? 'penjual')) THEN
    RAISE EXCEPTION 'Login dengan mode penjual diperlukan' USING ERRCODE = '42501';
  END IF;

  IF jsonb_typeof(COALESCE(p_settings->'metode_dp', '[]'::jsonb)) <> 'array'
     OR length(COALESCE(p_settings->>'rekening', '')) > 160
     OR length(COALESCE(p_settings->>'qris', '')) > 500
     OR length(COALESCE(p_settings->>'tujuan_tunai', '')) > 300 THEN
    RAISE EXCEPTION 'Data pembayaran tidak valid' USING ERRCODE = '22023';
  END IF;

  SELECT COALESCE(jsonb_agg(method), '["Transfer Bank"]'::jsonb)
    INTO v_methods
  FROM (
    SELECT DISTINCT item.method
    FROM jsonb_array_elements_text(COALESCE(p_settings->'metode_dp', '[]'::jsonb)) AS item(method)
    WHERE item.method IN ('Transfer Bank', 'QRIS', 'Tunai')
  ) allowed_methods;

  v_settings := jsonb_build_object(
    'metode_dp', v_methods,
    'rekening', trim(COALESCE(p_settings->>'rekening', '')),
    'qris', trim(COALESCE(p_settings->>'qris', '')),
    'tujuan_tunai', trim(COALESCE(p_settings->>'tujuan_tunai', ''))
  );

  INSERT INTO public.pengaturan(key, value)
    VALUES ('pembayaran_penjual_' || v_user_id::text, v_settings::text)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

  RETURN v_settings;
END;
$$;

REVOKE ALL ON FUNCTION public.agr_seller_payment_settings_save(text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agr_seller_payment_settings_save(text, jsonb) TO anon, authenticated;
