PGDMP  +        
            |            test    16.4    16.4     �           0    0    ENCODING    ENCODING        SET client_encoding = 'UTF8';
                      false            �           0    0 
   STDSTRINGS 
   STDSTRINGS     (   SET standard_conforming_strings = 'on';
                      false            �           0    0 
   SEARCHPATH 
   SEARCHPATH     8   SELECT pg_catalog.set_config('search_path', '', false);
                      false            �           1262    89438    test    DATABASE     w   CREATE DATABASE test WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'English_India.1252';
    DROP DATABASE test;
                postgres    false            �            1259    89448    admin3    TABLE     X   CREATE TABLE public.admin3 (
    id integer NOT NULL,
    name character varying(30)
);
    DROP TABLE public.admin3;
       public         heap    postgres    false            �          0    89448    admin3 
   TABLE DATA           *   COPY public.admin3 (id, name) FROM stdin;
    public          postgres    false    218   �       [           2606    89452    admin3 admin3_pkey 
   CONSTRAINT     P   ALTER TABLE ONLY public.admin3
    ADD CONSTRAINT admin3_pkey PRIMARY KEY (id);
 <   ALTER TABLE ONLY public.admin3 DROP CONSTRAINT admin3_pkey;
       public            postgres    false    218            �   J   x�3�N,J�+��2�.-J2,�B�y�\�P�� ��+�Js�L ���i4� �%�q��qqq ��8     