PGDMP  5    3                |            test    16.4    16.4     �           0    0    ENCODING    ENCODING        SET client_encoding = 'UTF8';
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
       public         heap    postgres    false            �            1259    89445    admin2    TABLE     �   CREATE TABLE public.admin2 (
    id integer,
    name character varying(20)
);

ALTER TABLE ONLY public.admin2 REPLICA IDENTITY FULL;
    DROP TABLE public.admin2;
       public         heap    postgres    false            �            1259    89448    admin3    TABLE     X   CREATE TABLE public.admin3 (
    id integer NOT NULL,
    name character varying(30)
);
    DROP TABLE public.admin3;
       public         heap    postgres    false            �            1259    97645    salaries    TABLE     [   CREATE TABLE public.salaries (
    sal_id integer NOT NULL,
    salary double precision
);
    DROP TABLE public.salaries;
       public         heap    postgres    false            �            1259    89439    sample    TABLE     �   CREATE TABLE public.sample (
    id integer,
    name character varying(20),
    designation character varying(20),
    dept character varying(20),
    sal_id integer
);
    DROP TABLE public.sample;
       public         heap    postgres    false            �          0    89442    admin1 
   TABLE DATA           *   COPY public.admin1 (id, name) FROM stdin;
    public          postgres    false    216   �       �          0    89445    admin2 
   TABLE DATA           *   COPY public.admin2 (id, name) FROM stdin;
    public          postgres    false    217   �       �          0    89448    admin3 
   TABLE DATA           *   COPY public.admin3 (id, name) FROM stdin;
    public          postgres    false    218   w       �          0    97645    salaries 
   TABLE DATA           2   COPY public.salaries (sal_id, salary) FROM stdin;
    public          postgres    false    219   �       �          0    89439    sample 
   TABLE DATA           E   COPY public.sample (id, name, designation, dept, sal_id) FROM stdin;
    public          postgres    false    215          `           2606    89452    admin3 admin3_pkey 
   CONSTRAINT     P   ALTER TABLE ONLY public.admin3
    ADD CONSTRAINT admin3_pkey PRIMARY KEY (id);
 <   ALTER TABLE ONLY public.admin3 DROP CONSTRAINT admin3_pkey;
       public            postgres    false    218            b           2606    97649    salaries salaries_pkey 
   CONSTRAINT     X   ALTER TABLE ONLY public.salaries
    ADD CONSTRAINT salaries_pkey PRIMARY KEY (sal_id);
 @   ALTER TABLE ONLY public.salaries DROP CONSTRAINT salaries_pkey;
       public            postgres    false    219            �           6104    105837    dbz_publication    PUBLICATION     g   CREATE PUBLICATION dbz_publication FOR ALL TABLES WITH (publish = 'insert, update, delete, truncate');
 "   DROP PUBLICATION dbz_publication;
                postgres    false            �   9   x�3��(J�L,�2���8�K2sS�3��q(0�N��N-�� �wd���� �lu�      �   �   x�3�(J,�H�M-��2�,�L��N,)J�Ṃ�kh��X�[������o8��8�K���gs%f�%�d�e�&C�k���,�ᕙ��A�(5�s���̼�b9�)x4�N����;s�&�ф>ZTa��<؊�=... �R�      �   M   x�3�N,J�+��2�.-J2,�B�y�\�P�� ��+�Js�L ���i4�J,��KI-����� �4      �   1   x�3�46 .cN30m�M��9���ҖP�� �0�1`F�̈���� �      �   �   x����
�0�s�>��}8wE2��.��h']��M=x�T�T��4����qz�����N��ח���;�0�5��������ɞ��ʵ�kۄ
���P9򆮺3p�ͫ��A�
��inOy�(f<vsT�q-P	S���%�TT�XsQ����k"d�*dT�Y�+��س@N-��kÊ7$ސxC~X�z��;��     