PGDMP  -    $                |            test    16.4    16.4     �           0    0    ENCODING    ENCODING        SET client_encoding = 'UTF8';
                      false            �           0    0 
   STDSTRINGS 
   STDSTRINGS     (   SET standard_conforming_strings = 'on';
                      false            �           0    0 
   SEARCHPATH 
   SEARCHPATH     8   SELECT pg_catalog.set_config('search_path', '', false);
                      false            �           1262    89438    test    DATABASE     w   CREATE DATABASE test WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'English_India.1252';
    DROP DATABASE test;
                postgres    false            �            1259    89445    admin2    TABLE     �   CREATE TABLE public.admin2 (
    id integer,
    name character varying(20)
);

ALTER TABLE ONLY public.admin2 REPLICA IDENTITY FULL;
    DROP TABLE public.admin2;
       public         heap    postgres    false            �          0    89445    admin2 
   TABLE DATA           *   COPY public.admin2 (id, name) FROM stdin;
    public          postgres    false    217          �   �   x�3�(J,�H�M-��2�,�L��N,)J�Ṃ�kh��X�[������o8��8�K���gs%f�%�d�e�&C�k���,�ᕙ��A�(5�s���̼�b9�)x4�N����;s�&�ф>ZTa��<؊�=... �R�     