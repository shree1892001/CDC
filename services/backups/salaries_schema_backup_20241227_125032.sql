PGDMP  "    2                |            test    16.4    16.4     �           0    0    ENCODING    ENCODING        SET client_encoding = 'UTF8';
                      false            �           0    0 
   STDSTRINGS 
   STDSTRINGS     (   SET standard_conforming_strings = 'on';
                      false            �           0    0 
   SEARCHPATH 
   SEARCHPATH     8   SELECT pg_catalog.set_config('search_path', '', false);
                      false            �           1262    89438    test    DATABASE     w   CREATE DATABASE test WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'English_India.1252';
    DROP DATABASE test;
                postgres    false            �            1259    97645    salaries    TABLE     [   CREATE TABLE public.salaries (
    sal_id integer NOT NULL,
    salary double precision
);
    DROP TABLE public.salaries;
       public         heap    postgres    false            �          0    97645    salaries 
   TABLE DATA           2   COPY public.salaries (sal_id, salary) FROM stdin;
    public          postgres    false    219          [           2606    97649    salaries salaries_pkey 
   CONSTRAINT     X   ALTER TABLE ONLY public.salaries
    ADD CONSTRAINT salaries_pkey PRIMARY KEY (sal_id);
 @   ALTER TABLE ONLY public.salaries DROP CONSTRAINT salaries_pkey;
       public            postgres    false    219            �   1   x�3�46 .cN30m�M��9���ҖP�� �0�1`F�̈���� �     