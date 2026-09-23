# 演示猫照来源与许可

这些是给「演示档案」用的占位照片，全部来自 Wikimedia Commons，许可是 **CC0 / 公有领域**
（没有署名义务，也不限制商用）。它们**不是**救助站里真实的猫 —— 等有真实照片时，
用 `python scripts/seed_showcase_cats.py --cleanup --execute` 把演示档案整体删掉，
再按正常流程上传真实档案。

重新生成这份清单与这些图片：

```bash
python scripts/fetch_showcase_photos.py --fetch 16
python scripts/fetch_showcase_photos.py --install 00 02 04 08 09 10 11 14
```

| 文件 | 原文件 | 许可 | 作者 | 来源 |
|---|---|---|---|---|
| `00.webp` (113KB) | Tabby cat with blue eyes-3336579.jpg | CC0 | AdinaVoicu | [Commons](https://commons.wikimedia.org/wiki/File:Tabby_cat_with_blue_eyes-3336579.jpg) |
| `02.webp` (449KB) | Calico cat, Lebanon 0.jpg | Public domain | ولاء | [Commons](https://commons.wikimedia.org/wiki/File:Calico_cat,_Lebanon_0.jpg) |
| `04.webp` (175KB) | Cute grey cat with big eyes.jpg | CC0 | Laurie2002 | [Commons](https://commons.wikimedia.org/wiki/File:Cute_grey_cat_with_big_eyes.jpg) |
| `08.webp` (187KB) | Stray cat on grass.png | CC0 | TylerMascola | [Commons](https://commons.wikimedia.org/wiki/File:Stray_cat_on_grass.png) |
| `09.webp` (154KB) | Stray cat on wall.jpg | Public domain | Neal Ziring | [Commons](https://commons.wikimedia.org/wiki/File:Stray_cat_on_wall.jpg) |
| `10.webp` (198KB) | Stray cat standing in the street.JPG | CC0 | Tokumeigakarinoaoshima | [Commons](https://commons.wikimedia.org/wiki/File:Stray_cat_standing_in_the_street.JPG) |
| `11.webp` (468KB) | A photograph of a cat lying down 0002.jpg | CC0 | Asabae2752 | [Commons](https://commons.wikimedia.org/wiki/File:A_photograph_of_a_cat_lying_down_0002.jpg) |
| `14.webp` (357KB) | Yellow Tabby Cat Lying on the Floor.jpg | CC0 | Asabae2752 | [Commons](https://commons.wikimedia.org/wiki/File:Yellow_Tabby_Cat_Lying_on_the_Floor.jpg) |
