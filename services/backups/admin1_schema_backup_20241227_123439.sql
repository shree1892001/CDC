PGDMP  '    "                |            test    16.4    16.4     �           0    0    ENCODING    ENCODING        SET client_encoding = 'UTF8';
                      false            �           0    0 
   STDSTRINGS 
   STDSTRINGS     (   SET standard_conforming_strings = 'on';
                      false            �           0    0 
   SEARCHPATH 
   SEARCHPATH     8   SELECT pg_catalog.set_config('search_path', '', false);
                      false            �           1262    89438    test    DATABASE     w   CREATE DATABASE test WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'English_India.1252';
    DROP DATABASE test;
                postgres    false            �            1259    89442    admin1    TABLE     O   CREATE TABLE public.admin1 (
    id integer,
    name character varying(20)
);
    DROP TABLE public.admin1;
       public         heap    postgres    false            �          0    89442    admin1 
   TABLE DATA           *   COPY public.admin1 (id, name) FROM stdin;
    public          postgres    false    216   �       �   9   x�3��(J�L,�2���8�K2sS�3��q(0�N��N-�� �wd���� �lu�     