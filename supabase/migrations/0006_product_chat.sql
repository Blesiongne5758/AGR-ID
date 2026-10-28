-- Pesan langsung pembeli dan pemilik listing produk.
CREATE TABLE IF NOT EXISTS public.product_conversations (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id bigint NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
  buyer_id bigint NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  seller_id bigint NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (product_id, buyer_id),
  CHECK (buyer_id <> seller_id)
);
CREATE INDEX IF NOT EXISTS idx_product_conversations_buyer ON public.product_conversations(buyer_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_product_conversations_seller ON public.product_conversations(seller_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.product_chat_messages (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  conversation_id bigint NOT NULL REFERENCES public.product_conversations(id) ON DELETE CASCADE,
  sender_id bigint REFERENCES public.users(id) ON DELETE SET NULL,
  body text NOT NULL,
  is_system boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (char_length(body) BETWEEN 1 AND 2000)
);
CREATE INDEX IF NOT EXISTS idx_product_chat_messages_conversation ON public.product_chat_messages(conversation_id, created_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_chat_single_system_notice ON public.product_chat_messages(conversation_id) WHERE is_system;

ALTER TABLE public.product_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.product_chat_messages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.product_conversations, public.product_chat_messages FROM PUBLIC, anon, authenticated;

-- API PHP memakai anon key, sehingga operasi chat harus lewat fungsi ini.
-- Fungsi memvalidasi token aplikasi, mode aktif, dan keanggotaan percakapan.
CREATE OR REPLACE FUNCTION public.agr_product_chat_start(p_token text, p_product_id bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE uid bigint; active text; roles_json jsonb; product_row public.products%ROWTYPE; convo public.product_conversations%ROWTYPE;
BEGIN
  SELECT u.id, s.active_role, u.roles INTO uid, active, roles_json
  FROM public.sessions s JOIN public.users u ON u.id=s.user_id
  WHERE s.token=p_token AND s.expires_at > now();
  IF uid IS NULL OR active IS DISTINCT FROM 'pembeli' OR NOT (COALESCE(roles_json,'[]'::jsonb) ? 'pembeli') THEN
    RAISE EXCEPTION 'Login dengan mode pembeli diperlukan' USING ERRCODE='42501';
  END IF;
  SELECT * INTO product_row FROM public.products WHERE id=p_product_id AND status IN ('aktif','lelang');
  IF NOT FOUND THEN RAISE EXCEPTION 'Produk tidak tersedia' USING ERRCODE='P0002'; END IF;
  IF product_row.user_id=uid THEN RAISE EXCEPTION 'Tidak dapat memulai chat pada produk milik sendiri' USING ERRCODE='42501'; END IF;
  INSERT INTO public.product_conversations(product_id,buyer_id,seller_id)
    VALUES (product_row.id,uid,product_row.user_id)
    ON CONFLICT (product_id,buyer_id) DO UPDATE SET updated_at=now()
    RETURNING * INTO convo;
  IF NOT EXISTS (SELECT 1 FROM public.product_chat_messages WHERE conversation_id=convo.id) THEN
    INSERT INTO public.product_chat_messages(conversation_id,sender_id,body,is_system)
    VALUES (convo.id,NULL,'Para pengguna harap waspada dan hati-hati dalam menukar informasi yang bersifat Privasi agar tidak saling bertukar nomor kontak,alamat dan email atau informasi pibadi dan sensitif lainnya dan segala resiko yang disebebkan kelalaian para pengguna  diluar dari portal Agrid bukan menjadi tanggung jawab Portal Agrid. Terima Kasih',true)
    ON CONFLICT (conversation_id) WHERE is_system DO NOTHING;
  END IF;
  RETURN jsonb_build_object('id',convo.id,'product_id',convo.product_id,'buyer_id',convo.buyer_id,'seller_id',convo.seller_id);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_product_chat_list(p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE uid bigint; active text; roles_json jsonb; result jsonb;
BEGIN
  SELECT u.id,s.active_role,u.roles INTO uid,active,roles_json
  FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active IS NULL OR active NOT IN ('pembeli','penjual') OR NOT (COALESCE(roles_json,'[]'::jsonb) ? active) THEN
    RAISE EXCEPTION 'Login dengan mode pembeli atau penjual diperlukan' USING ERRCODE='42501';
  END IF;
  SELECT COALESCE(jsonb_agg(row_data ORDER BY updated_at DESC),'[]'::jsonb) INTO result FROM (
    SELECT jsonb_build_object('id',c.id,'product_id',c.product_id,'product_name',p.nama_product,
      'buyer_id',c.buyer_id,'seller_id',c.seller_id,
      'other_name',CASE WHEN c.buyer_id=uid THEN seller.nama ELSE buyer.nama END,
      'last_message',(SELECT m.body FROM public.product_chat_messages m WHERE m.conversation_id=c.id ORDER BY m.created_at DESC,m.id DESC LIMIT 1),
      'updated_at',c.updated_at) AS row_data,c.updated_at
    FROM public.product_conversations c
    JOIN public.products p ON p.id=c.product_id
    JOIN public.users buyer ON buyer.id=c.buyer_id
    JOIN public.users seller ON seller.id=c.seller_id
    WHERE (active='pembeli' AND c.buyer_id=uid) OR (active='penjual' AND c.seller_id=uid)
  ) chats;
  RETURN result;
END; $$;

CREATE OR REPLACE FUNCTION public.agr_product_chat_messages(p_token text,p_conversation_id bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE uid bigint; active text; roles_json jsonb; convo public.product_conversations%ROWTYPE; result jsonb;
BEGIN
  SELECT u.id,s.active_role,u.roles INTO uid,active,roles_json
  FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active IS NULL OR active NOT IN ('pembeli','penjual') OR NOT (COALESCE(roles_json,'[]'::jsonb) ? active) THEN
    RAISE EXCEPTION 'Login diperlukan' USING ERRCODE='42501';
  END IF;
  SELECT * INTO convo FROM public.product_conversations WHERE id=p_conversation_id
    AND ((active='pembeli' AND buyer_id=uid) OR (active='penjual' AND seller_id=uid));
  IF NOT FOUND THEN RAISE EXCEPTION 'Percakapan tidak ditemukan' USING ERRCODE='P0002'; END IF;
  SELECT COALESCE(jsonb_agg(jsonb_build_object('id',m.id,'sender_id',m.sender_id,
    'sender_name',COALESCE(u.nama,'AGR.ID'),'body',m.body,'is_system',m.is_system,'created_at',m.created_at)
    ORDER BY m.created_at,m.id),'[]'::jsonb) INTO result
  FROM public.product_chat_messages m LEFT JOIN public.users u ON u.id=m.sender_id
  WHERE m.conversation_id=convo.id;
  RETURN jsonb_build_object('conversation',jsonb_build_object('id',convo.id,'product_id',convo.product_id,
    'product_name',(SELECT nama_product FROM public.products WHERE id=convo.product_id),
    'product_harga',(SELECT harga FROM public.products WHERE id=convo.product_id),
    'product_satuan',(SELECT satuan FROM public.products WHERE id=convo.product_id),
    'buyer_name',(SELECT nama FROM public.users WHERE id=convo.buyer_id),
    'seller_name',(SELECT nama FROM public.users WHERE id=convo.seller_id),
    'buyer_id',convo.buyer_id,'seller_id',convo.seller_id),'messages',result);
END; $$;

CREATE OR REPLACE FUNCTION public.agr_product_chat_send(p_token text,p_conversation_id bigint,p_body text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE uid bigint; active text; roles_json jsonb; convo public.product_conversations%ROWTYPE; msg public.product_chat_messages%ROWTYPE; clean_body text;
BEGIN
  SELECT u.id,s.active_role,u.roles INTO uid,active,roles_json
  FROM public.sessions s JOIN public.users u ON u.id=s.user_id WHERE s.token=p_token AND s.expires_at>now();
  IF uid IS NULL OR active IS NULL OR active NOT IN ('pembeli','penjual') OR NOT (COALESCE(roles_json,'[]'::jsonb) ? active) THEN
    RAISE EXCEPTION 'Login diperlukan' USING ERRCODE='42501';
  END IF;
  SELECT * INTO convo FROM public.product_conversations WHERE id=p_conversation_id
    AND ((active='pembeli' AND buyer_id=uid) OR (active='penjual' AND seller_id=uid));
  IF NOT FOUND THEN RAISE EXCEPTION 'Percakapan tidak ditemukan' USING ERRCODE='P0002'; END IF;
  clean_body=btrim(COALESCE(p_body,''));
  IF char_length(clean_body)<1 OR char_length(clean_body)>2000 THEN
    RAISE EXCEPTION 'Pesan wajib diisi dan maksimal 2000 karakter' USING ERRCODE='22023';
  END IF;
  INSERT INTO public.product_chat_messages(conversation_id,sender_id,body) VALUES (convo.id,uid,clean_body) RETURNING * INTO msg;
  UPDATE public.product_conversations SET updated_at=now() WHERE id=convo.id;
  RETURN jsonb_build_object('id',msg.id,'sender_id',uid,'body',msg.body,'is_system',false,'created_at',msg.created_at);
END; $$;

REVOKE ALL ON FUNCTION public.agr_product_chat_start(text,bigint), public.agr_product_chat_list(text),
  public.agr_product_chat_messages(text,bigint), public.agr_product_chat_send(text,bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agr_product_chat_start(text,bigint), public.agr_product_chat_list(text),
  public.agr_product_chat_messages(text,bigint), public.agr_product_chat_send(text,bigint,text) TO anon, authenticated;

