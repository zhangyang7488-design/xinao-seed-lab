from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "xinao"
FAKE_DONOR_BINARY_PAYLOAD = b"fake-grok-donor-binary-for-sp-b-001-tests\n"
FAKE_DONOR_BINARY_SHA256 = hashlib.sha256(FAKE_DONOR_BINARY_PAYLOAD).hexdigest()
LEGACY_XINAO_COMMIT = "b916f8bd22dd38b4807298a4c935f6bf2969eb13"
LEGACY_INSTALLED_LAUNCHER_SHA256 = (
    "18ee492eec5d89c07bb9c0a0aa2b8c797bef923aaddf4eb2bfc2d7dd53e2a76b"
)
LEGACY_XINAO_FIXTURE_MANIFEST = {
    "source_commit": LEGACY_XINAO_COMMIT,
    "files": {
        "SKILL.md": "5b5837cc012cefaf6633164f3002a206ccdd4e6745d3439e17166ba876d35960",
        "agents/openai.yaml": "1f72c9c22b1687dc767bad4e45fb68db4ab702aac53ebac7428fa61e284779e6",
        "references/capabilities.v1.json": "1873f056c2ebd17f0ec1cd2f665bab9695f72e36f9b1c07d5cb4fd0fc3a1483f",
        "references/meta.md": "077a39b60c723f04157d6bffdb44aca319b900795f6efb79f445a6e1815f0cd0",
        "references/researcher-charter.v1.json": "52ee3f88426c36e4c27ee6098157621c084812efc14232157ce5f231bbb8850f",
        "references/researcher-output.v1.schema.json": "345d716de773495a35a63688a027f065b293e7fee0d1533c4b20180245b11dc0",
        "references/researcher-runtime-lock.v1.json": "561b895dad2bd08225d3a45ecd5f1160913b0ff679ce736bdc96e34776513ce7",
        "scripts/xinao.py": "5fcf87736c46e244005f4049771440c4c1f049860bb55a318151ce23c3a42e5f",
    },
}
LEGACY_XINAO_FIXTURE_B85 = (
    "c-qaqS$DG9wkY~v)@$xw6Eq}~)7pNBMii?=kV4*6ED%sW6^)*D|NHHI6fi(c{Jy!)x%(k4iNYxQ=yf&z_rJ`Z-tYfA_W$+2{"
    "?#|7V>4FPGsk+-JL_Z?Yo}&xMDyD4GIbl$)KSxqpz%3x+n0%JM0&^Ad1fQ@93z?3G|6*DE2kZ$6X);MJhrc%qg^Jo)oNaku7"
    "2A->TNCcnvKNo3|4+@U*@&wG>h#}Z-1TO{e#{fuIFtnm^xpH-;SdB<#}bhLzu_kd5#j{J8VvQUW32e+I3nVtR_zP<h!Gll1$"
    "Ia{^i=2*WGcbed?VqtleJE<KeE~Y+O7TYvOh{(>A_4Jk7SodJ5ytw}XS;8SW;Iaq=&X^`tgD`HmvZFXxrF?Vc8~o$75Pn$)5"
    "z!T>*qaV5X~70nzw^_yqh?|IhN6qsi-abb)&I!s+d!FlG}ZZxSI$*lGadsO+{$!u${VV|d2&^UPkz_)GX@T(0I*fYS~OD31b"
    "apFYj48HTs=apHrqj?jbkFI*B0b{IiJ!jY({B4mn&&<YY9vgUumxbA=&+6U1=jtmD-T@d(crFu10oZH7yry0zL1R5@pI2~B0"
    "3Rix=b@fGGA3DLJge*Q{Tj{#&eqk_W*{B=qg_wGyvNc0JwELRy=DY^MLej<k>75mGsp0Ia1I`v9qec0xq}nHOq!U=(QAgQNo"
    ">Qo-3VX;@K?5Q9$N|{E%b1|a2~owaj}3OoiNokGFQ*3mGMTY4NT=1>??K6HO%Wpa6ajzW?%c?JliuH((KXzy#0dn8m(qE<p8"
    "i-m*!phwe@LUvwHB347derkB)PW3jkZh5uKh5!MWLX^s0Ao4N(l^5&Va<tN|Whd~(Jzz;q}9P09011Mp%9w4}k=s4?LC#dn7"
    "ifeXd`7}gQ>SG%4OtDGM0<8}bJxkdbKTqpHzGVd7Iex1Uzzij}1M(MoXK>S?kZ7-R_-2I@@oo&6-v}UcQKv#Y(lBRFTit~Z_"
    "MSX^`*RzXqUWjuy-;RA(lRdItfWiCM5%~n{dp#5Bui5zW9s5e~YNM<^F2F<FZsNxl;N;hV;`I6ow6vSJ!yVwvp&3U&13tn!B"
    "y<6^1>c|Nv09rtFh>CA<{AV}NS`xDl>r7g#(EZyR-Wr6UK?@10@$lSqezd+755J~e*t(LW(=qN4*bvPaT3EgzyrOv1n_7W;r"
    "<yP6ZeCE%d^gCHFcgTjkJa*nD3dM1)TkM$mr;KWwifZ&0<v|{K>VGIqX}YEBO0wc4n>Bq^2Hc4$gP(A)ob|h>u<}Yg?3;bcX"
    "W0(;#>XYX;mwcq<5Rz!Ur6HJ^LU&;Z&|PVnw!R<|X<mkB*Tz=>KEAusacXe07VIFBph7Qk2bfLD<9!F))QuxCZreBdv~XdX3"
    "Av)UQf5&>Q`0EdTrhJTldGejQRo7WA(mtd?D;66NSlQWwk?R0=w)yX-X;0!mjnhbo@rufqV+JU_T+%_l+tk?#=PtLF22O0o*"
    "0Aqb6lWiB)jI<1EiN6#oFX%Zmx5Lep&}9Vh09jF6uknn4A4tekk=_VB*8Nn(Eq2Bd;xar#@C@Kaae|D2xHAOYB5>Wn_g7dW;"
    "eQ;40Ke0mti7?uGoAsR;rZJD=LymkIrAazBkemL$lVCf5$1{z7HfRZ>i|sxe@4DBi#>q3%=t0FYkDq#10Z97&-6yt&@wIcqw"
    "f;D0NFFby~c2!6y6{+5w8mJ0^o@}2cBDl+z0?iQm>72<9RiX?Ha*Jl*4U1!TH$Qa{PZw)?Qmq=Jg@UxKwY!_;q`O{B~aRWWY"
    "r@SB1bE$3odMW3&sj&G{_AR+AV%E6UJL7jPT#xXimjF1jGsK;BG%20(tKKqJ7%v<vD8K+`pt6F%=Ah}?7tZXNNA+4<Ix?|9p"
    "gz;T9a0DSZvf0yYQZGyYKIeZTL34Ir3Rg|*tkHB-*x+vcOejsm7c-~~6REELc>?80w*uRJHi)OBU$aE-2qC6JhL}1YN558li"
    "&DDSZ_rLz1e@$15?eXx}E?I1+!M`ulI09V_@DFga8v~6+AFCbg*#P(h4BTi5`#ySO_$-||hmYyg;nEmSYZ1U)@9E9PbqaLsY"
    "bx;EA>eIvrhFKmH=o0&h4t&heA)1KpBAg=W04%wkGIvrNz;Yn{rUi*LY{NX&4)AEq>I=6B6vS7oL>Ai{YVy$mMj+2^~d6M`v"
    "idh;NRir&gbqz)&aEUt$pW9a_hjCfbRWwSVIIn(0mIQOb<d{2s{w!HwBoK@jcU*eAERm!ue5tRM1V~_Ze^jcxNO5z9Fm=z^k"
    "CS1-=1vx)|?pU7!bjoqSnMW^Us!b%qJRDnWUO<1igq0{$Ga^Vu(!i~V9dUmX6LPm}2^h=OCVIQ;u0|9f-TZQ-yMXV_S?3(R("
    "n3~iYyzk&V&pL1b)C5NP`1>|=@Ir2d9^gCUpzny&P!5J3$21?rzHuANcI-}qtcncW7g8mzwi;aZ{PLx(14|vl`2hHa*9|IJx"
    "5a*t6qoof_W(rERTSG-GN?n4yYTYB_HvrMT;9%%`AlTvwATR)?Hg$(dMyNPPOa&i|Qxbgop&7j4_a!0*7-$C^ccpjO?`G+_P"
    "L%C4H!P45$s%K6dnfM)MHuT}{mmQfovnd9)4c+tgK_L75l|p}>H0;cQFuO6*4#Q%)?}59VUe{N@4J)Jiath`y0k)jY*?B(lG"
    "aNrvOnxrG&D^0iVC7<G6f3Wr-Z2%6gUbyuE41qU^>WLq<)-Sfx!lJO%0Xrm*N-QcLB+5HSwAR$AIXya8{p#5;fc)gZGQDDBu"
    "YgCa|V+eimCWh+u7=P1o<c19}$iFBE{0M;Hs9pTx#&yb5C%@wpa-6wbLp1;P*ZXTOx-{eOQ=TM)(_<KV#=19Q2LPi;j8W9es"
    "H+H#>Z`ja!O1I_LGC``6KC=jC~H!>OhGB^+#L&1x53QY3rAg-GmDH+aQ$k;eeN{sIneRes5-<s5e-zBCNFOE~{AP@|_l|}f^"
    "d8JI8_m|$2q$I&dbG6&RGu!>I&hC`V;GfSZejW9iX#k^`&%XjLh~DG4_xEa4Lm{+Uz4V*!iem1#0k8CfG5-Ief2hjj*Gy4<w"
    "G_`h!RK$vOK?@DFH@K|QYKHE=jUb<{(o0qUe=1zY-jIGo($#r<qY39l;>DilFQ*`((Ed`G{MhcO-zWPU|YO~Pt(Qr!<lW<;F"
    "Lb0V4Kc=rBgq-5p3{$x|r=#r@L9iaRfs1SDHOD**`7%`;WywctQbK7NU+3e{doC^fw4Z^{{Y`;YT1P=~O>H!PujHwBCPi_ud"
    "SCpSG#;xd9}`-`jn%jKbYDij~(m>c57k?mpV~Hh{e2-TGx8?RVEW=)S}Mukq%W8?C1<{Cx$h=AHb#dHFn@^ecI1pS*52`}Zi"
    "A)Zz2}HlCe!`~7>E_V@5Se)iWk>TO_d9nQ~5S0KnYi$%IyEJo{e>h06`El!<!vM^uLbSj<FxUqYB`g`+XDqHd_!izi)Fvh)2"
    "Tbn0mb|Q+zVjIG~lN8||r0~8Tr3?K?;5uEcpPUrnuZJIwo&XH@1m@*A<M9b#zgg|KiPDMo)7f^{9dCclW}wAylJNDF?BfJ5T"
    "cc(7>i~v>21+3sH~LEX6|9xn<&)q?KYaz9St~$z@H4>AUiwd?mtK3IJpZaGyJmxY)_ZCwyIQLJYAVVuZ~*TH@Ee|cIx79ROK"
    "@@Gz;iFp0JCs|dv7*cv)XX)xqUpxD16?4_IQPJ1j8Jal^B+b>zTd;Fjif8Nl(g4t*gv_*~+YqxV=C;eto?Rlzy$POwA#om3}"
    "ZJxSp5_;Q9pC>nTZX{o?(yl$Yu2OaDbt6bJXxY({AK5d-+5e=Iz}Z#7yto&91u+^2Y6&L`kH;4c0~{Gaw#fdBY^vY0N{h^x_"
    "XKSksGgPd(2KA#78E(`o0_v+|WNyPtyr|`+?qy%peCmiJnXBClm9SyYomtW_798X`972xpk#SPOv;NWhAhRK!iSscqn#So2M"
    "7h#vIpX<B5;sTD(kRIY~a@_{|Sq$G%JPigL9o7x=0(~v!+ouH#19PU%=l&_!t`=aboOiv9N9;d#%49l#bKY?t_PlG(mHn@g@"
    "&b4<{WvQxi!<<!uHt?CQu@DU{9Sm?hclTO&G&7rY+&u<=;VC@JxOSAfeg_=UwV%>`Z5W38$!41og2Y6qy6hC+D_h9XxvWGIa"
    "MF^#QDitPM&by7sZQr%CB0eOoCU$g%>Z@a19yH?5A&ldpfR%;NP#OPvzHToqa!h(q5+RSHx>2S=3&pzXk-4`|w+DYWU8}ES&"
    "((hVcAX=D7H9=D*&6r@U?f=Jhb`)pyCuC!E2a!~S&Yo{)FMTYZbXA`bdX_<y$BO|H9S*NG34ejL5dV&E~`sQVY3+uO?4))t%"
    "*(7U4nPP|6xv<J8dd=Soiwd(=g0e|C~;<YERUxn;{_kz6M1$uo0e1GE4ym*WBW!jri+6adHIoRJ5ey%973i}=^AeeEV!}nH="
    "(tGd@u%NU*d1=Et7fRoY7Qoq~^zT?ecOAv+4Vw8{{Sf$3yoiC{Q+nAynd*ti5#;ygU%SP$u}3}*_`Z6Yy1?_&I0d|Wn)<7!x"
    "C8jlXblY`^Yyfd{cY;}4LA$*Gra<@L_VnnAMvjZ(w(HegYNh_4nX$y{sMgJL|f%Al%GB2IXwWs=o9(a5BkbJcm^2Rc<vk~6k"
    "nf)00#qboytxQKY$T|K{8c<7Hq=PIQ(DJv68&Z0VhxJZmjg5eBdV@;U`qi$MNf!=mQau?m@9YPN2MVf-T|a=3l_etu&XP?lC"
    "32VEzk@#t*W8)CpG1mdPBGljeK0(OtwjJ_naq$Oq!X%LZuay4y`DU7em?#J6bk+y^Cw$hdf;z!;NxPU}nuAaI$%{`$cS@=Ya"
    "4C1u)Mz%w8dY8$2h(x>NdF7a<Xf4%LYe!lAyel!Gn9juU!02gbF=Y!n1>^ScQ9BRXNCxBl|nWZq#R3o@NeF8eHy*1HzZQJX4"
    "%|#kYe(kQ?ZTByf+dxOF)kxCDKqIpw>JQCErvJldgY{Ev1|LKox(PaA&{>Vn8DfmXXHS`N4oq^|O`goZwu|Y2@#)X_1J7Xbv"
    "ioov8|3$^Juq98OF-lL33Y{d-|Iw&F3@!kz60GMc|IY3+a2^zK_|fTn;rn)={i3MUV}`)^99*~d^p$lKsVX$cF%4UO#gy$uP"
    "}zznUbJQEkb^aFwglW20WC+16$Ak5FHP(4LaKU2KBRMBSu?r`nKomB6?9UU6Qq?zhEz~u&1QIjb8yz`X^NKiEhOCQ8dB5^rN"
    "KT*&TZ>@+!j5g57R40ev2W27WW=;V^!(0(b=d_vrZA$8+25pF21ozzy}L_iZrQ0REkOg!U#2;5}21^B78#@sfVmoC2Tk09~a"
    "-h9_}~pDD9N1ibm>#rt?7uz5{w@?7F*fM0WzIf|Dq;Mun#zh>wDjiY{6`#MZwZ8NRCBaLvLjd~K&OL$67xPCkzl(Ae_5oIgW"
    "f$_W<U4uMDy*;BdE^m+~P;PP_#q=1$Z(dOz0c}k#phKBoKx+~CT)8aCbNi_dpD8GxGC2lx2(;Az8Vz3h(;n(JgzxR0KJa^+z"
    ";-eP8Stwo%JpWt=mB3vz2tR+yoTF{?Y9+yJMaO$-B|mv20Ta$fG$^rru(Ue>(Ase@&w(SA`bz1vI1RfNIvtNxib0qRHn5F@&"
    "Lj^LEfNU#MhRcHOOCFC(zF8X2Iyv6xW3Ot;=Z!&xPpq!LLmefUHelcPpc&u4hOSj<E(imFh{0pbqlqR|NFDd*XUG(WyZPa#F"
    "Bq<n>3~2^Xk8$Bpob$l8*fw_h9<)BSwC*#FmjJ>4G{``>qAmE9OS_*=qQp}%Qy*A)8QE*Nuh>!RuU77WbibAR*3pUcP6RE$|"
    "}Jd@0Inz!vVbA#pXpyk9dj#GD-ySrj71#>!&L1}6pcZ$?HnEpFh_maBK)a4xg#=vI5RNkPkK6ka*HTZl9n%5CjV8yLz60ARE"
    "<1l|ctSxh2bpseTBr!W!2fTNf*DUTXfHkWJwwK($Z>wv+V~|+PtfnlfPdsyn1Z?iaBW{kyEOR|{4gvA^lJWZ6V7A@vbbvLwE"
    "NXV*)z%V$MdWE#6fMnG)G?b~HFps-UUeGtCuaa+63DLSz}{E-){mx+zw@a(!ZGZw=Su6YA+3U?nY$nsmoC6hj>tTzqky^FO&"
    "7%P+l&JJfUXSBiMG=Yb>Z2eZ92B9o0hNZTj_9TFNpr20!X)e2_Id9b3RqfKep_aY1_kZ=H8tYptWRDG56P}eYp=mAoB&94t-"
    "GX0)W9Degd;%4K3A$`RV#K{LNiM-8Ib>P?qz$eV$Way%593c`{d4Fo~m-#K~n9aZ!j#qMOPC%Xb)MYsI{PHeIK;wIz&YxHaS"
    "C*A#RwM*zPinxxa%-Z0#z@wCj{)Xh{8;+D>09@NE%v5i?E$1qL;7Wc83BO#xB*Esv`i0}ej|B}0tWA!pYGZ<*ft=X}M^LGk("
    "9#pt3VecBc*EWLNFu+*h6y_DyjA}x(h^^e6chAiSY8kR(k?u%LOjD0=9#P?QnxBF0M})bAISih#wv3mcE7xrtJdE|M?zz|m*"
    "1JoONqR)idw~DrX^{czAxyl3g|8`tTT6bYas3GXK25hUQ6Mu0-AZ9W+kOp$u%6Vv>gU1c?Kl|gr|f;k-26^-=8Sa`Cz$xa8S"
    "vU`8wo)K0JPO1jQ5iH><h?+%vzJDE&)RB&#x93Igq%oG(Rkn>F3P4@Q#fE@r!sEQ`p0-ZtU<~SX=fvCYns!YAAk|Cj!{Z86X"
    "Dy9abWEP21!QUj5}cEUAGWA{}pwew79YF@rPaR{=o?oQpyZnFadxhm@IYc_Kz0GzNqLT>!=-aRN+E5tz+Z@Zkc(f_2I>lfXL"
    "wo8iM~MXix-Xs+DVMwa0bCLY=otM%0#Ns;AB%BP#zlU+Y&pm*U;<`HlN83n9)P8j3NiPAB^(gWDzeg>{obxwagM(JG3<E-b~"
    "E+JO<JHZ6Aif6L9mcqCKUi`<#ti&tW4+th{;Wi?skbq4={P*y8BmsV0Z=NB6cnlhMRpESo#!DPWh$-BsYtB%Oa7vS4fWh71u"
    "^8{mnIlP7q5E<!-7N0X&lME9H%xeQkso#aLM)=pL&SKW$PXw?fH~VoHrLp;8>6w@wG3-S=Cdv3=Cg6A0*-5AOS18&rAM+LsH"
    "reu!im!2)==g|AU0+>+{xLKI7-F)7qm|^TF%}lYrhbMj|+7kQ{lfmKQR7%x;+N*;=iKZJp8AMcfBhUMbZIWY^$3oNpfR6aGQ"
    "VkZHzRQ(XKpDy!F9$JRFD3XPL_luMUcWtZruQs5}lR@p?KKw=Sh;L%_AuJW^q9ZOd?ztzX_@V$#G3k6uj$UI1smNqExYktJa"
    "PZH7mGV;w=3U51;t`d~BXvT6&out#NP2Fiq6qsd}ITyHlS>+*23yMBzlXfhsMCL8_gwXNsDc=9~l*x|?fq&BR1;SlIz2+G!^"
    "reBBSmNJOF^>AZd1~nTj;0Am*famqv0G|68`x{WmvY0&3y+q>ZGNDb9s7K)!0nU7_fuDqKtqXW!Y(a4Vr2-UwO$EHuFbVGj^"
    "jB2;V?Tm1;rU@6pRZ%Gs}X${pQi~|_L3xAQRTh$5vUW>QW|4fH4S^HjqL8bsi`K=k!4!4)~E5oi2LBc2qOOee!Y+swxr1zU@"
    "K!XE;o?2pt#jBk!$p592{fm*L*H<4n1fB4FR1T=KCNy9{&0Yw$t6elM7G-OKn}cHBZJgJ%HkpreDH{B-Kwj@f6JYdDoj_%1^"
    "y3k(8i%12AY9VJabeKExdZHv+Yvq%?*8TY_mHByDPnDJ7U*wh}%=Elc=+Rv+YZbcQ=0IjS%QNWp-m4qfMG@$={^tV8ylC~U?"
    "aP?@yC^jtD8rt`7qE&S{)0aaE#>K)`dB&{g>e&i^a4mn0GjHsofUC)w^-Er#+PC)&%n{TSFkyPQGD^tvL<-ZfEd8h|Jwst*J"
    "!IUsGL9fnL^P5puGr&|cEaly>RdXz<mi{iSO5>g=SIkpv^;Oa`EU#f(UzRHmEvAutj^)wn(`<|Y=DS`;2P{eE-(rdVMYARBu"
    "Tr*zo-{)P)~4BG%^=VJ;rIj#-A*+Y_C~@!B+a&4@NP@9OaYejp!@z2ec70fK9|3q7w?1GKt890<6Y#yyU2`-b+2w)li{6|YU"
    ";3uRRXZ}yOwOAIXnV5=>)!^-3C)z8;8RTZv9I!OJE8b8fF7!86n|N2a2}fJz<R%=hyt3O7eW4M@(m&W7=qtr$WOSe%iJ%f}f"
    "=&4Rynk8?M}F*sT@97{>H8Sm(z`vWs{iNTI%?0*wN0H_5n}Wy1E~%g;d_jHO}!x5sz6B(sjWl;i8)^^8z8M`6@5S_D7rab$G"
    "C^k3R7wGS{EBdmK|x)TX^6u2x&Yt1z#p49}Lbq>!V#}lmzfaig0Vu(jT2g$rMD!e~KZ(XF4j3was8_|>{>3oh)$|^if4Tx6t"
    "wgVj5^(G)WFycT{-Bb-U)YCjzn>-uI0L^e#*OL#H$${Bfx~48+OiW!{_ArgMJvrzdrj?O37!gPf&}2c|X(JB=j{d$|p%&9K-"
    ";SR_;{#1zJ|=aM3}w{bdd)C(F+C16Sl}T$m=80s4!u#~S)4OP^O>aK*ARXdo-Na$6qF>PSMd%X56_4HT>*#2JoaVcTF@w82b"
    "cg(`^dvU5-Jtnhc7G(C-j`j%A;`Gk+TahWgH{VpqY$+f<t#b#fS?lOJMNd>0$I?hw3}fad#{!OQ6S&4U!e`ZtP0<oi;Furiy"
    "8!!z*ei0J9#J*myx>39@73f`;T@R*Bw}p0FffzS*%XrYtQz1bPzWmI9XkeCKsWDbVUW@Nje|VoAku;*OA~1I=I-(lF{Z_5I-"
    "e?FD{_w(JldwCgc^0a@3&49DJbvIWb;9qfFt`h6?~YIhaTCaw$~h%+3HFg94D@pCRK1BHz<;qNE?cpWX;U|E1{@PX;w&N<l;"
    "nFshs<Xkgc^~cZT3^?2|T^lT*v}&E?-KK(gh1wNeYcmw**-RV-G{Xpfe^u;H4T#H&&C9;O*<(+%1lok}rd|gu#7;IArnZA7N"
    "A!|4x`?J@xy>}Q6}owW9zhmF*H7EHkmmvC(NzTJ337a(!WkWi1-01)Ju_VOfbY9)p7HkvutXUPbYm9ac$n32?_^Dtu=Lu|#@"
    "CLN-dpGvm-zl9(5heZOt!Zb+Y8bv;idif>jc)~wMR>h2u%Zz0vN5OUYo85EuT-b3-WDp`~dmPc>z4L@vvl~x&8!;46I-E0{B"
    "nI4U;j@NelQU@>a&z!qvnbkoO*=IWh*y_lBXV?U5A?s5RJ#_3iPDy1)|Xc~P^UCv^#6+MqfV@bU?>mZ!iANI6Cuvk?{4Ind2"
    "2oT-t3^_=|9dd5<>XIMiEJu#LIf;j|h6iacCuTVH<Fv@VdgB~?ZE6&cfK1VNst<qAankLO^ax%HB$-aPp6I}=PS_2%Dk#AL;"
    "Ggz}bEUiQOz_C)#og+=7e8V$l_(}0(9K-ix&U4s#GgoFmmiI6|SwD%4b_S~5>B@-Pa9#=Q4Xl>~`z*}HSU8A3L^lJTucg3GN"
    "qJdDt8CvK9>nVcdNC<8d1v}?Qz79Rw?<s;J1@}FMV+pXxb0mjUDVWTA1o%&IT8=}%+gd|eb<J+6{24c;WNUEIuckg@>vh~8v"
    "O)I=)`&Zv3mBL=bgS?2Rg$^JUf8lu_O~&*@QyR%EYsY2tAhMA%8B0y<Vrt2L+k~J0kVALuD2NKV$RsW6XTA)7d4*6~xsE>KD"
    "WUR3a=_#4->DBjB@`DL&Zs_!-g=1$vs$MnMZY1-;<_c)suPl8xBEJvaK^1!V6vD;Hw)+iP|~kCH(j)|%s%P4!Jp)j-!C+ZuX"
    "<h>T!-Ib{0;JLMwCA`Eq*?Lx{E&usl+55PiXGx1;qE4mh9yV0_Z`4#wD%|;I;+8Q&2m795~c0AK}<JU$nOh;cWn^cA)E)o3Z"
    "&v%Fy1WQL>NEsOF%<rwsfM*%E(StkO1Dypku#xb6hVQ*h7CK$D^fxHa`(f_t_cWd<GNfzd=g}6P!TCU^nrySIk`(pIqMZ4HG"
    "a6wSb?cLG1@K|fD@XUL628(N*0H3L;)ovtkHfHIanJM};Bm0`ja*v4q1mBgk6U79^BdxQh~Ak`x42fT6^)GBaijTGR||IUMH"
    "!iPLo0aF;QSYz5$7M`7+9usA|b7-1bVO$_s6TC^e#U)mFPfdXEcj2nPM61HIu#UJBHisDCTF&%7C)6GtU{NoF7v;`?mfx-_D"
    "Qlei3HOTQ~yS1#GV&=zm_rw7xW>kaf?`coHE0^xx%IEce4wQuGv|ZBBGPYI~>zcN`h%U0u`!nvf4?*OkaQp-%hh9*g^7pF7v"
    "x1#~}rwg^uSmt4mb-_L2XX25wKL65G`Puu)Eg45Iwf;=0;am`iWp?!uW+ktonq;xK%*|B;-2LZm2Anq1zo>gG9)OS;|O;;KY"
    "Oj{kA09(^iI@F`i*U+dVzos(X!&2@r=k>WB&E~z`U*@4)XKN#Sg*m|9T6;B%{r{tGCBl)&KSJNyk&jEF49pu!|K1MIXh-VVT"
    "(;lGQg5Vvq`~pzoXN>fS1IBpm80_uoB`8M!7g5VAP<UoHI(2yfM)nvfG$+C&;GZ18S#&Sd>Q=aIYq;f<!fmFSaL%f$;J}S%N"
    "bc;U8Du{-4Q$JxAig`OGXbshf>cZrK1Ow*ZjL4rQ0uBN>1<$)`_Lg#v02Yxz0go2lW>`!)Ew@W^Z@&JTkXn|A}RqF8XA!!s)"
    "UGeyd7c*Sqz<Rp21vW+dI%FG6%ktPneTxgCa{<R#3z9&D^ykCf(8-xHnloX(t4P?SGnC7M#3QTq9DygWlqC;zkRwRGMIZ^kc"
    "G$AE6+qppc5Ge6HGz?9GRogeLXZsr?{{%o#twHi--`fg67^LfW6X-HT$I<fyFbBpO0DUVLyTLbbbB3o^=Er)wp3yq*)gh#a7"
    "Nra)o2ORvSzb*)iaxupC5n8rajH2XgpftgKnL=xcfP5D7))NA*b|gW!1o~@7#D^kQSN49km2=!P(Z5=>yTQimfIPA=&5HV91"
    "zFb-syNX`0hw5pA;9=nP7jQ>?$Q9s5O_>>7S_jox<$Vf(c3Hb!FBiq_>?&J)&mBn$9Y=-x6a!FsI<H`QfWDD4YMpjH|27<MY"
    "Bg9v#EV;9NMO74VSj0nuPbtUGz_Dn9*Q^-9MJQP17=3hV}f&KE&!jjCeD@WO-jVm8v2fQlvese#LAKnufG4k9%PH`-8rNVFT"
    "6)`}peGTC^M!drIw&Bd-B}=l%oq>r41u*JD0&(U&05JmRPrVQ-L(1`$^<^$JU+u>>94B9wWf_$<of(tgQ!0Pk?>5IIb2QP_J"
    "ltAZh`;sqR65y!u)<YjR71$YzrUVJB9>0@a%pz^=KYn*Gt&*|)@0uuDsmWtUPdDgELJak4;SF<F$VTC|Hc6T|Fw9&`{d$<)@"
    "j;(%-K?fMwMAvVO!Y}Q?Gh=!|&LadL5c+m#Hju4m^5X$sl|73(gIgm$yd{mjtl!O+X4);JBf1s=&bf@@@DoyO=XGq4WMzDcw"
    "zPPd|Ku?^m=|L^G-E>@iF6C!H>}9etcb?MdfX?`#<mJwfCb<e@Rhvf1g7Rj(X4G;ajzvk$ILUEXgdzOM(~#Cj)h9vQaZ8UR?"
    "jr@e*bxFS2L^o7_*T87RjVO2yQY)cxIfYX4xnFnWf;@DW*Yc;mnC>C0wM^RxX`E%Gy3$d910|&Qh$C-^E{7Ha@|Ie|KeHH-V"
    "QjepAUy@19Agae;LZ924S*l=io@wTW9}txZZP&U4J7s$-m$u6rWH&phN^`QB2ngFt})oEj_o$*ODzHfQG3r7d*m9yq>dDYeK"
    "au#FS7AE+;(=vTYvA8Xi}p^<na`ldDD4>ItI(0(6TGRQ3WKZNhX`2#qg*~umQrMPA>Jsfl%Y%g`icm}rYLLVZ3-np<0C?e0g"
    "KBMFMWAaI}fM<M=>_J$k6-J-1-mXDEL;iOwt6Jr_boi4D&CeKgT0yoD8?^9U`MhpZp#S*%z?SQ>xI!L_m%1A8dyH3$88jWtZ"
    "+Kw8nH`qV$x5*O#Ec#E-%|e~$OVvl_L2Mf$?wdUNLz+QEb}JMeQ2W}9Q5}%x{w$Zr5&FAGd87YFxJ$u4eQJD0<!fBc@?q&vV"
    "q6n!(3kF**=fXnZt|79E`<(GjE>Hk>q?P^V_hT5S7>f*w)W?6biSu9G+SA7U2)HLXOK!7zceav&vWr^%<9K=<=LPB2()k{0)"
    "pba-Mi%e0oX!+QcVTIIA1`jO7Jz{fF8yS(}?IXQDX1PJBwl$D`30QSWAM(FV!h<L6VARmgRtdnG+=O$Lmw(spCP<2J}hwoT0"
    "I068-nqwPWPVTgD!998j;+x>8Q$}0pl^_=-e$TMpef5_Iy<PopBw3m71wZX<k|C^36S3Z8U=#aK}+)ppfgY|h<qwV4Z-H28!"
    "Vwq9Cp3GjyI6K%qH$3llekGZ+ysRGM+k(A&vscQug*CoE#Mey2`T{ycUM4rjVFbKw2>Mq9vR<)32k_wYt_9!Oz{j#PXrs?Li"
    "m}YWt>1}VmTckM{e>WNZ^k(ka{$<RMQo3`Z!GhRy0t<pM$RXRjBx7IM~k^|IgiYBYD%+rZT~Fh!*mWpTj)=mI+Qo(`prt<>7"
    "?!73)LqK66*o}(3ou_zd{#%v;$POU(y{X@A_2XbF1q9bmQYIbkcz{+oCQz-$t1AOtL&hAB1b(*NM6Q{~_23pi@+o>J>7-SEO"
    "u@w<EPxo)foZt@M_e9*x<mty0+%eV?>^b!$RP((MrSfG^*PE-VXncC&VF`_(GCP6@aHdnnuPw{XaPVug-FVE>JgezG&_NIbr"
    "HS(Nk*E{pmV{0rMza{fYSpZb^zC0CSxS-YG3ilVM|FNXr?5xaIB#Jv>rvEbZD-W9yt-xl-5iu@hc?R-gi_E}e~8p|VV3S-3V"
    "v$x_pm@Mb?(<`j6sqnUYg_v5AmVP*sq7B|Fy|)r&0i_|~Y;Jiwc4SJ5_?Xc~75}I5XtTS^KYwGaYTxgJV+wju5x2N6SCp?Xc"
    "GVax4s{n!;`gQ4w950A$~rK|pUltE?#e)$p@`$T--hT+FPUzJ`79mMGVlaA!gE<bzR-+#z{3Riw8G=|Kg)=$lNj|YW6nu&Zj"
    "1?I27is@T``?7>-fbwVS&8JKg<2%lm~a1Z<<wn=~=EOjf;A~cRZ8m8O5~_J&?yW3$c=8(HBO)GYaGBJieDAkE8N+bZ?zJCRt"
    "c#-!0}u)Aba_BQcw@ek1tYXca*mUCFs%>^P6fu{pc6r7?Miw6@(bdykAoV%*z^;%`w;dd%-6skTMzx8dhFw3lNm8e5=y8W$E"
    "T3)UrgWcnKCDMIY_5P-~(Xq8juPek4E*eCfcn8S)~CA%26rMVeJTuSozD=E88=FNitEt`|J=O%FCEh)n(=q8KDY}oM_bZzvp"
    "+30(;)s_i%sbkVT({+b=PKqNZB>zRj%8ch7@O97;XjK*9Sq=6^a%gEq;aVG6Bb1LM&*alB;%v`Ee~W?n87ZlXa^H4B%sTSS-"
    "<ii)EJ!|-t?H44d2Ds>T`r$j%5zluw2JGT>vPyz{!n2j<=q2mO~HR8h9&rH$h_Rn+G6{9Sl32~kI+`k_WzIZk?Q>WJa?1lY!"
    "Lr(p8LUbs7W<fkl98gPMG<lsw=*@jg{pc%-dLMj#W`v<yJ`eFOi!?7~ZY$LR<;*oYPqiOVPVE&oP#;2dsof*+lpr?)#fO5A+"
    "L?@q0Xe5#EkZe2aJHz<31cJw$geefJ2jy46!c-yBQFrP0FJLU(Cea>D?cHneWnh(^J!yl%w6pEJ0Ay2so`)bjK2I+Cyl%qLQ"
    "@hT#HsN#QJ(W-(tWg8|9+wy)Ht5@N8n%3HSY$}*t*Zhvc^X_d3MZ?Q{fru!G<#JyN_QI>{>igD0yaap)j=eavhLEaR{;r{v@"
    "7pOlQuLS`7Dy}{6P>Oj#N91!KG`9->KHPa0^F&G2Amx?!>=~-#;Byn;fiv`ZP`Odk1HZ3~yo1NZGY^uy4Syi&bq!MS?9-Su!"
    "jH;HrlV&0y?65O1=xxH1VQJ<7{H_yCzM!~s{ES2ACWno>+Wk9$tu^axLyiy*%Ess$f`{XJpE&P%ye3Y^Nc?+os{I-5glMwh@"
    "CQgE5SPed-ULy^ZWwo$aJ!DZYA(J#*aw8uT?rf)GLg&cPYLn?(ODzhpxL1Fe|?YFz8sJ+IJ-bbRjj%VFErudBe7x8~A7Ap-&"
    "0MJWa6fX6u!C&+pD5#4CsTh*a{z`7=J^TzsLW5T|M1FY_)ugUQwg7>}@R{I+Np0^bZ(+twQJqmD<?S{qy1(vsE<#AVnEqk-Y"
    "9TVr)?z%#f%hvR%#2K+1eYWk+ka6$$>dS2W+;P<T@uH2(wXQNy^{<Aq*4jJaFfqcQZ)7Weg{s*#v<(|oh?Kiny+nYSnYF+wJ"
    "ise&1x=34h^g6tbhUNFZOJ5)FZ|9uvk~~bpZ#W%t-j>l*o<m9Kr1-8~&<WUhT-WG&&9biYwVnWPBDs~#HPaiojsW^I&@PP^V"
    "m$Gv=K2GFFaPewzpSa)Z9D=S@m7Y!(Wzh2B?Nu=>?#Y|&Ie>Y*tev@yzg?`jb43${<;#6N@f?O(!bx&D$WN-UJD62FR3`EmF"
    "z+cJ}A-GH*00}uuNx^8T@40>AGF5dpy48JWed;i{-S_t>6zg{>g8~=XI=kcbz-)upB#Mndf%>!F<~r8$<K~Wqe5N<UpR2b6-"
    ")}cR6+bPP3e{f;?qD=cb&{D}Qi)K`&}&yx`kBPuDE@K8X#ar3-V-ahuXs8}w0==I!u0Gn#{hpP#eOFc(SGqcKMZWc0Pqx~5="
    "#--9)oOdg>x&>nmj>k#-t@@H|s+^2|jQp}DKIx*bZlf_Q|S>7hqfml9cK__B3bQ@nmJFGN6%a3IKv|<dgEp!<Y{f%UtQdgGB"
    "PDVnGVlj@H`v<Gy7Db=xi@4^p-l@l|W)04NLUrdtjchsA!DWY_SK>Rlj(S5AxomJV`-k?9m^f$hF5y$4lTVy^nb#HcXaRTbJ"
    "Xi3UA^gfR=N)(>*f;Zl`MzG4X2`$OM7!lSSC-F_$(om<ZOuQw6GP&*oWRS<HpD~z3wYlswmKBMRz<XS&lX!b{>CjBC0T>KFH"
    "%X%zdR<zaZ+8De51E^OHdJi0lS&R#Q?VoyhZS}SLD*&#%4=(f8-_+JImn$8UI#QEA(Bbv{DD6+*YZMZDh8jfcuqWar{oa=C|"
    "K-9v)Q2Ey{RQwWbF<*;J0tcqpy&9G<a$@J>wU1}7@(oSGR9tY_O$h*ghnWE9q`dOTiS%khBvxz>Bn4HJ@=7&P#2BDZk8llUt"
    "_UpAaoIKLGA)Ia6tjazoZl5Eh;jpaxJo1hhq@k*~p;_=>Xj#H7h-{botobJ~hSH&!a@z2HD)T?aaHA$IYPLx@oKQUQ)KgU7v"
    "w_z>e%u%J%-h`MIt@R}Oydbl0`<;|K7!jF#=Y}0-qhq`hbX(sYE`=NguKN^x9u@g2bp55=hEl8}LSL`mLLZ4$*dO}DK_1~vL"
    ")l&{cu*M*NipB2TbW}*a0Tp*Wr1H6a*JLc<WnzykT3KzZ=<;ig1+#59JeB;ht=s-<<I=aSc0x!{=AZ3aa?^!Z^_>I4##keN?"
    "ge4r)obKZv`By+t)m<n#FM|$NR0=x47n?;^0;Ldn_;OPv`y-c8}(8-HB=6#2WrD^9Gb(qJOOdCrFOi_jt3}-Qdk{<?czth9#"
    "@-V@YX)oO-vLSxohYCl&OfZ+csl-a809Dfy|U@%MOBo^!zZH3@CX|A;4*b0q}*>aHF15AsIDwTaJ)_Iv5`ay%j9Rh%cNN3dz"
    "5d$twYmCUZ9xfOXVxoo@fJ_iZSE&2jIUj8=EYnkW!<u?_`xB0u@)V%!9%F`9DseC+7SCE%n?iBT;8@gh9FVJ~aK5TxY1?Rif"
    "^5KEpSaB|q*ZuiCe6OWg>m5Fy2syce?#B4}-FM19-K@4k+)t6-^IVl1_!ju|V>ub-So#`_Lhap@RSWxr88+zndH&!}InRk#s"
    "Q(q=%Je?W-7b7y#pi!-ePD->S{721Xhq|(rCB3smG^lm$o9f|MVJ-skaEwe+cCtv^?W}!HrTDMatnik?(<-+8rogm#z;CY?U"
    "rU5l1+L!aoel}hr9SA+A!bIFj;d2?LSyIYFlVGM#j==VGcd1BYGd%L$n`1jPR>Fl1D;co>HE*8TNkE{kK^ydhtftN`HTMS(S"
    "JAm_P9Dxt0AtkLdk3G}|*DlEe3ONB((fEj$+yeQlaVYt?OOBCDh~U+-4t{-o;*Ilq<q{dYX>MUXq(e^~Mvg*WSeP!9Ys_Km("
    "0e7pCbVSmfpAJx@)9O8e1o{73d`wOqI*#Dqw7IK&=53*aXgna1mvtD`^C;kuMd|YAI-|dlcBhUVmy5f@dwu#WkO7vHN?QZVc"
    "h_@K4$a?nxtd_IdB>$h+b8IU6=6%zHv*f>x0Or^~I<{7%&zQFEjzjGe-X-x@A7t3n8I)@C!8QmQYs_87{zUA0^32!R2mU(ig"
    "e%X*x=+l@SLT^s$<EQr##^mC?1SNaVa_vNHGcuwp3E<ebarXby5vg(doh8YPx=vLxuqoMo_F<cvpQX~kzHTZ4;t3AZLR1PNY"
    "BTt%YU=D7Jfwz%!zTj6ZWM;cuX7vZwNolx7b6^kUWyZ0J5V^_Lu6Kv4gd;dQ0@3vbtVUE0NXplDtT-t=4B--bau28ko66p9q"
    "ThMD#WEb4fI(Z+P<1AC7ggbsf(d=vTXVO`&H%^Lb^o|7JDAEbe5Y4|#~^1N$Pm2;^!R{F}hrO(OieaLr9;a45ru-`Y%`#kDt"
    "OcAZRC&x*Z_#v>`>J)boTYqLYU)o+qm5bMi5I_7<xkmocuB-hv-032=9=jeHZT{gb}zC>TCzAEN@jNHMI(!g;Iw0-inatW^*"
    "u^#2JT<>Ty@^g0W{cBEFit4s+adMQ=RB}7+_Q?8)8ZyxPRj6J6-M*>G(*8<?zNm~2v$_&`ZBd8dR?h+*DDUyw5N@hz1aJlt!"
    "Eb_hUkTD-)*B~ij0nx5e+Tgm#`WD1!tV&UctjfzXeODFx~BQ60BgKS<Rao1!&ji!>80`WZ62EaVafIg^f}CXY7sl6MRIu?mO"
    "Rw($7qteI0^gS!uK)S`tweMtOajYEUiaE+`zrguqQLo!yCLGL53%Ve#AoUn;<h{nj=Va0D4*c)~c+5E7dXce$zM4WwjW^eiu"
    "SdmdwsA_O%e}`SR=Lim`+2R!QEI<gr*(kMmIAmn^RNXrGILVQFK-Rxxi4^l|ll+|tIDT&!=+*D+Y}b?6<IYm?WlBfNnh8z3W"
    "|v;GDoXM*(+!`_v8b5-oah<bi`-_>zgZWG_;CFW<F>3UdeU5dj|dp+;5Sb!1c@&L{srobzy%}&>hJ%vGLkY3`9Kf+qTmZE*|"
    "mRT-+DOTsVfe$#(B+gbG8{wp{#P5IV|6a7&fAW2HKY`|!*r&m?lqJabp<xe4BMa+FJmA&cuF(QJ8Lyiw^|KXy#E;}n3$=Y&{"
    ")_lt#ktZN&a7wLk9~^7+_NmV_qX~S3vtRUmk@B=Y}sRyS0fKue~YU4u+Yzi#!U|eTrT8;@jWT*Hl}iH9(_1su0!@bfep}<!f"
    "K^?kK~8X+{7D(S{l{C<ze5nz6P#jn5N|sUkw@iv04ei51jd}zOADx*NxMBIpR0rx$sMtKa%CW_Y3ogJ}#Oc!sjt*4<>|3{`_"
    "P0<3K-J2l$%U^8<Tu4o9}}ZVEjQMc)U{-6Hobl-4rB+kWC`i?uIEzl*w*@bAX_z5F||zJ}$raGw5io+R&C^i!_n@8y*Z^^p~"
    "Q2>E4VKeapO@%Y*SA5u7L(BI|kHl#V`BewG%Ok&?4ee+xA*a1GMSt0fS`nF!^b|1HWR1ZS!ywFosCi=5mXE`b6`be&EeE(gW"
    "i^{Ya*rbB*VNBx^Rz@%P<ch1E$us>+;m(6XZ>`*~PxPBB;VE3Mwz2mP^33X5e{PrdxSvL#1Afm&M$220J6`DP$=}a=KNf3V*"
    "}H2W`@c|sh45WP@AmfkG^hPpvR(oi{kPSt-@46N&U@C9JhaMpE9h0^GaN=)9yP1`V*X75CXe|wKS5@ryhVTJ&%B57)!Y42J}"
    "Jg8P%iFf_52wN?=&DbX=LKLc-uii|08{>AM^2JEYw1tKzaaS@0^x5W^`qOUf6QM9vN#P!N<yZ1>IE#UNUa#yq6W|dF#TuM>X"
    "wi;H`R1c8=Q7@BP6#v5y_fwz1qO_OPWey*p<imeTBk{VC)90!Qq#<zu}IocH{iNSFttb6o^<vmV9IjE>>FWc1T5EcNXF!@Z0"
    "{6@F~jl^dpMd!U=xfH%Xcy5AxW)NHiNu%74>@9y~yU&j2VHwkaa%X#r+i@EWB^dKKDt=qOp{ick)wbVBD3$N<WIYs*Av9(YE"
    "{z!5%huEV5d0^qL07kET-3Higyv~&Ng-8FwTfpzh;`;3f<e4Q8RCdiR*rZ-Ek&F46;(79UoD1fvP6GFjaFEVjjyGjzmiLn?+"
    "Eux}OJxhKqqyM%V<J0@OrLOM&bxAblk{wnRXUEQvbeXkqdhId7p(mtJuf*t+vKLybV7WWq>pZ~|7Fy5@l2SmOWvhAE|rV(jD"
    "O}j>`mX8jIZT#qh~6_H;OuDpIuvw>(ryKIkn0D4uE!6y{3-7SM2+X_`~n|sHj29YMOp~d@i%_b9RSB#rSyl*_!)*Q(|MIonE"
    "+~s5^IQjP?XD16YGSSfe*j0?r>jQzi0`=jh$;r;y*9=f*Vus8>>vHZ9dA@imMC7HP8N)5>wFPkKajB^PXgh0E_s$#{xj*DFh"
    "J+XWd#?{^@2GQa?Il<Tx^0H6Jv>Ml>_bNaM+IbGQQwW>SG_;;1}nVpI?>ZCp+2K#4AujnQ|X^!*E$H4VA@|^%vYH#Q3rhK5-"
    "!_ouT`t**1%VWJ7FkWdRZHJg!B-quFIvmR&_lb>Byn9KgV@AGCZqY>BY|isfP4Qk4yy=$Q)O*RU8s~aobNy{UC+5o{c`sal@"
    "!cV>L*wsqnI@CF#7u!V(c3=R=d@mf^}EUPB=WV<+gIJXP3{T1y}zIsgW&yCgdB*IkLQ3f7sMe=&2Fyc{dYkYgf<zg;HPChd<"
    "*`9^4`!_S;IPud8DSkBQMFCwzT&o#(E05Ui6L)Hij`P?o*Lxwn}=4VLwX!{Tc6IxmnM*`@=g%XrI&s^WbQlh15w9IY;R3?s_"
    "WsM0~^~jtROd;ta|?tlMBZA;BvV{xqIax~G8RM&?&}@Oi!-X@<Q%v9B!fj~`%5amqdfej965zLwMvrd;(%T73p@=bz>Vy9($"
    "7-urRQq}NXQ`6TP}!)>chZpZeDF$CrV)~;?%joJU%9X&ty>dD6<zOX#bchhSm>j5jy|JyxsH5+^6Vg7xQ@4p4Y+%!Jr$Y;!r"
    "E6h)Nujca$_qSzt+u%KKa7JH)%?j*C`2DU+|7e}E@d-N8faLE`f2we!JKo_jj64VBOzZN|Z1ksA-h(&yEuJfC%+9M)te4*DR"
    "o!c|bT5n$ZzX-n%YJ?y%l2r$5K@b12|nzboUJ=|v;Ka6AVcncg3jHrZ9{iK2OWpTz$o1<Q|?hZvTeNcs?@8O={T@Yw}!r5*c"
    "bKLWxXZ9c5TDE1B~O4`HKCw#eCiqsWs+(a%wpob?kQ=GdXX{{H{mx|DsM~Y<g4qv}C*|*jATj_x28%Z+i5U`<u+_15yjqy>#"
    "*3FnQ6`w~yKHU!bGg6Vi7nx8t>O=%akc-nxcuMJBtiue5iN*{oi?(BqZnjurAe(I?FFHSjrF*IkOyZ`YT3^mm{)4=cPYli;0"
    "8YHU;B5%pf%kou8rjV`2@(8Z(mw>v!m1JaRTO{2(c+QY7meE4loV-)baW6LmKO759^C--gcJa;|&*tGC&mqM?QZ2cWlr<B#F"
    "kbb%#XR7=|)Zd@gj?(XVe7U5vm!9SKeFRnGK6;lQi+g4GnbkLwd6eUn^z>S1_eN*;TDEB|9q{=5r$uu&@){*CCUH*J!+0B!1"
    "EhaA&Cg)HPlf!coHtQE_Rnfmm-#pqbtr=W)vXJ%2J>rjeqYL8VSB(ll8U{Rd%e4L|1u?UxP<mybdA%@i8ej-pXI(ko_oyK%6"
    "d$l1vq?PZ&f)S=6kyhJb%msOZ|EmZBoz|>}S6iL;NYP2G5x4&+Vv2;`W$NP~h_+iR)L~4_dsBEx#{pGpjcg+9zdw@BZn7Ua>"
    "E3gZ6ozqR^A;kr<3~5o;m4eipmHSSRxEW_9nFzNxQzmyGY+vul^sW|s0^_w3wQ95BD@kivd;dq-Tx|0`-MdA>?jO%?W5A$Mk"
    "0^@<|3l2!FJAXmtJx-1VVxbw_r;=Ua{>I<x@=W2{w=X>v7GoPO+p9*(ni+3T#e;;SDUGKXMpc!%><`(bf^$D-KvtJkN|IXkz"
    "Ye%H#Qq{PFvHo0HLmEg&u!WBxQ<ci^H|4%DLT{ORL!MtM*L1l%7xyDpzSjl%2OFnm-GiY7v>e}=^MrSter&t-KIlteX98Y-r"
    "D%it!PgaI=AW2X8cPSF%a5h6;dNfWw@w@jebbfe5PdY`<l<jop862w;sInU*k}`wA<+xWf%i5a`)%SgRR{0$^PqVTXF(=a*F"
    "RVL0I%4aBO-PG9;s6=_N}}FKkDbZb0?$UiO$|wCb@8Z?gtrT-zg=RfgS1K<Nc&yvwfN>lh0p-c7V4Z7I$fq`v0on?FC(F;Wn"
    "aAyoV<q9eB?#?59+azs0#TdH<i>Yqh?*R{I?T?^=)icj?4>yX<B);3YNGfmf^!<_9<k@u0$*HL38d*aK*=c{`MP%9i4GB<8i"
    "jJUhQ_ebW~*vm?sy|AC)sh;bdfOCgh4#d`obf6jDnzIM!sJrcQ69S<dW_{)3uJ!bJXlE*>w8)&c6;=SE>YzP*sL*2Us1H<p#"
    "to7~NdsVV{Ddu3*`8|{s_mEVtnZ^g-TaVYtmt%v`a76CgF8XH6XIt7!zGjrem3yFfG>UbLkH?Ig)pJ$IVIdDgzE?BI$I0m*p"
    "A~ib+i{Eh;$1H3@3-SmTw9v5I>b+_+TQ)9rvl=`g~OBTHS1ZPpF(>%%(o+MyW)L7>q%`@iGxL(wRIl6za99!y=9w%-zhwgWy"
    "F(1j)S*%p;oOcKRcQ)ob??cK1C_Hxihs{qF<s@R?JWC7v-@antyi_J8u?x|6XqI{<Y{mXYUW^F5Sv-Dm#m@>Ade;8$KHlJN#"
    "C5aG8X6i%TGb?yS)!IyL%q=NtKzo-^K^p|CrlyI>RRaE6WBzI=tdnLPqO&^Zgdpc0p2N%VoxT*lk8JBas14>$L5s8pkM$G^n"
    "-f>1iSPTSgY65BZcqrG}bKUYRi`p8mRc!&BJ{>OWSgqZui`Ac_C2>qYR{s7+lg2ouAJ+#^t;sq7GBue8J@31V!D}?*>*d0}~"
    "pz(_L7~=g_2D@Jfa~>S(htwRc0lazG1%2WJbU2>(A1oh<7gy*tg*)ZoZwfD(Cq0senx!$AmSRR(JOS?;-=ZC2gB^}JU}5I-$"
    "nMJ?Rq(r9e^`pK2yXxLyyRX6vj=;XYu!&9b5?;q;r!cFrr8dOiIX1YxA_2kFXcLWk|&_4mH9k)FF1=c=$O}VKd*<ysR<tyWO"
    "tT-z`xIPHuAethY{ZK`w#9x5$_er#;dF&WIi<Fr(u8JudNbeQ5=VF`txDW+K}eITf#dT+zQ`U)D^C2y&2(+SJpS67{e+*1A3"
    "VwOUdK?2M(qB$(ucVTbuWh<<#BY)$>rTW%b>>KlNJqhj&sGdRD#MwISeqO1dBGy<GV0whk?q9Yo&Ivmxg%$a;?Z=;JirS>DZ"
    "eV+p<v+~1+H_YCl0Qn$kT6vVWT8|FzF%W@u1b-r4qZ)iQ&)DZaRnf7-p@Pw@Q+{A6P$TLA@-|T$-wn}_8A1oh=^k^e_gqe;L"
    ";rRkwlySWw-5C$yZ;*Ue8t1m|k9V8jR5jii=<o`13~(cozS-vppBpp3P&K?j-*nUqIj1|YA7}od>b+sFYuLw`@tS-40(w;6="
    "N*y{Uo{TTWg_<)-F|<sS9(PsII<UV$L~$vY$Xf?TJ=i#O&=_W>6`qgZ^xT&=Qm?m(fs~<9jW^Bd-+s1cLX(xJh3BvN2kCqVV"
    "s!uGQ9Q6(x0LoUF=avV>DF8>ckhG_ZlO)1ZJV9@paH7{_<#&$6Cbsl9C-Deuw#n=c>DAZ+gH8@yCMwnDry2@7%o$p2ZA)V@w"
    "_|DBi&?+$To$m3w!}7xkIjJ&O8iR_kBZTmMNfQQq4U>npE>4-=i`QUBuicb)klkH5L+Ow2=xh+au@aPG;CA=dXUxh_$uXMCF"
    "rRK)|uoE+Mt^?sgG;o0h5UH9^Hep>7Oyq@abad&cdDs;C8bA2l1LoqMwhdq??WU9y9-XE*_y@p!C8Cn+r_%(|SjMvFC?1}Bb"
    "c~QNG#0CEo_vy{*KGB^}SDAN=@9<dE-4Whf+}m7MY0dIuePdZo4yiu{IivD*@!H@bUqN3usj1ES2}F0t{<EF~+;-l0PIMOU9"
    "WC%vZl@G_NdmuNu~uSdM=HQv1$~m(qJ{DLg6)KUG3v|4{-<`G*FTqSEOG}U`<v_ct|`Vj3*Y_le%`aZ)O+gwIQhM9bT7hPyd"
    "Lp=plz(wus6WGZSCl1$oC8W5nBIKk$d^ED&05wyYYWkgUIInx%UR%nH7F@4QUPbH@QoY_z}u>k$68M;g#AkqPDzJyjRgK>mB"
    "^AMAEC7_&2h<5=;F$P+kC^0=R+BM)8&OY03IF0FHy*_&=R?^1H5Kt~ssIB6Ul67YF^!N=NXw?~pv`(FE_gclo`-qzA&4^(JC"
    "|A-p@nCi%q{ACue*I9K!g>u7Cko<BR3C*;m5de0b~6WCD(-X|aMb<Hp95aq$A*(G=Nki5q%?}G3~p35za$;Qd{ChCD<;XWDK"
    "7v2u~u@-uS=E=Txdd$8rJ<p!Qc$-Y~v{xj4&UE-A<vr*(#C$JHwRo=Hz4d-SZq@^k=&!6F0l<Rd5Z+HjYIz<Si}Lu3Oz*8D{"
    "#n-VU?T-Y7m4j9i{<A%_Z=N*)<9Xz&Io-a>S5OIu0c;0@+)Z%g1hh(a(RTj_tcNoy=T(%nq>F}dQBi5h5VMFFZPOfFXq<px$"
    "o_JegQopAiWMEFV;}^P-(r*P5mTaZ<eDzbMXGaHI7*WdL0w}gw%**Y!G;I=gew%0FP;3P{ubStgF0t_biUb>drH`f_*{%X7{"
    "k{2s|ok@A2J!OzsIJ`PiRhsSraf_`d0TG`43J{D#0QwDSbx+N3A>st}LE-Zb~;Vzg1wuaw^z0epepc_Zeb-ic=ro^w%d?wiT"
    "`Ov`i~S#K}v=6=ynhrldle2@3Wyjfo{U)w&Ax-2?>&R^aomDnA;@8w0Wh=sBmd8%(PdN}62Id0*3t*Uny;3f1YS+o5Lxyns`"
    "7Br9Tu{(#UTrc&{#ybyoG`^sOKyPQ@vES(h$v1xayEPt#dzP6#GFa`tTLZ(<Gu|<J1-*jg?17z^@Yv7~H9Yw|MBj<9rkM7}u"
    "+=3y(<S;|(e87zGi_X9tQ7Ms{pOnVk-_^+nydf*?|=Qj{~xR9s#*"
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module():
    return _load_module(SKILL_ROOT / "scripts" / "xinao_runtime.py", "xinao_runtime_under_test")


def _bootstrap_module():
    return _load_module(SKILL_ROOT / "scripts" / "xinao.py", "xinao_bootstrap_under_test")


def _auth(module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_AUTH_PATH", auth)
    return auth


def _state(module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(state))
    monkeypatch.setenv("XINAO_RESEARCHER_RUN_ROOT", str(tmp_path / "runs"))
    lock = state / "researcher_container" / ".activation.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"\0")
    return state


def _sealed_release(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_character: str = "a",
    dirty: bool = False,
    variant: bytes | None = None,
    package_version: str = "1.3.6",
    capability_version: str = "1.1.0",
    shadow_runtime_tree_sha256: str | None = None,
    shadow_runtime_lock_sha256: str | None = None,
    researcher_image_modules_tree_sha256: str | None = None,
    launcher_payload: bytes | None = None,
) -> tuple[dict[str, object], Path]:
    state = _state(module, tmp_path, monkeypatch)
    source_rows = module._source_bundle_files(SKILL_ROOT)
    if launcher_payload is not None:
        source_rows = [
            (
                relative,
                source_path,
                launcher_payload if relative == "scripts/xinao.py" else payload,
            )
            for relative, source_path, payload in source_rows
        ]
    if variant is not None:
        source_rows.append(
            (
                "references/test-release-variant.txt",
                tmp_path / "unused-source-path",
                variant,
            )
        )
        source_rows.sort(key=lambda item: item[0])
    bundle_manifest = module._skill_bundle_manifest(source_rows, package_version=package_version)
    hashes = module._reference_hashes(SKILL_ROOT)
    if launcher_payload is not None:
        hashes["skill_invoker_sha256"] = module._sha256_bytes(launcher_payload)
    shadow_lock = module._load_shadow_runtime_lock(SKILL_ROOT)
    shadow_rows = module._collect_shadow_runtime_rows(ROOT, shadow_lock)
    shadow_tree = (
        shadow_runtime_tree_sha256
        if shadow_runtime_tree_sha256 is not None
        else module._shadow_runtime_tree_sha256(shadow_rows)
    )
    shadow_lock_hash = (
        shadow_runtime_lock_sha256
        if shadow_runtime_lock_sha256 is not None
        else hashes["shadow_runtime_lock_sha256"]
    )
    module_rows = module._collect_researcher_image_module_rows(ROOT)
    modules_tree = (
        researcher_image_modules_tree_sha256
        if researcher_image_modules_tree_sha256 is not None
        else module._researcher_image_modules_tree_sha256(module_rows)
    )
    tool_df_path = ROOT / module.TOOL_EXECUTOR_DOCKERFILE_RELATIVE
    tool_df_sha = module._sha256_bytes(tool_df_path.read_bytes())
    tool_rows = module._collect_tool_executor_module_rows(ROOT)
    tool_mod_sha = module._tool_executor_modules_tree_sha256(tool_rows)
    # Distinct tool image id from transport; both must be hex-only Docker image IDs.
    if image_character not in "0123456789abcdef":
        raise AssertionError(f"image_character must be hex digit, got {image_character!r}")
    tool_char = format((int(image_character, 16) + 7) % 16, "x")
    source_identity = {
        "source_commit": "c" * 40,
        "source_tree": "d" * 40,
        "source_dirty": dirty,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "grok_donor_binary_sha256": "a" * 64,
        "shadow_runtime_tree_sha256": shadow_tree,
        "shadow_runtime_lock_sha256": shadow_lock_hash,
        "researcher_image_modules_tree_sha256": modules_tree,
        "tool_executor_dockerfile_sha256": tool_df_sha,
        "tool_executor_modules_tree_sha256": tool_mod_sha,
    }
    source_identity_sha256 = module._sha256_bytes(module._canonical_bytes(source_identity))
    image_id = "sha256:" + image_character * 64
    tool_image_id = "sha256:" + tool_char * 64
    labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        "io.xinao.researcher.grok-donor-binary.sha256": source_identity["grok_donor_binary_sha256"],
        "io.xinao.researcher.charter.sha256": hashes["charter_sha256"],
        "io.xinao.researcher.output-schema.sha256": hashes["output_schema_sha256"],
        "io.xinao.researcher.material-bundle-schema.sha256": hashes[
            "material_bundle_schema_sha256"
        ],
        "io.xinao.researcher.runtime-lock.sha256": hashes["runtime_lock_sha256"],
        "io.xinao.researcher.skill-invoker.sha256": hashes["skill_invoker_sha256"],
        "io.xinao.researcher.dockerfile.sha256": "1" * 64,
        "io.xinao.researcher.entrypoint.sha256": "2" * 64,
        "io.xinao.researcher.source-identity.sha256": source_identity_sha256,
        "io.xinao.researcher.shadow-runtime.sha256": shadow_tree,
        "io.xinao.researcher.shadow-runtime-lock.sha256": shadow_lock_hash,
        "io.xinao.researcher.requested-model": "grok-4.5",
        **module._dual_profile_image_labels(researcher_image_modules_tree_sha256=modules_tree),
    }
    tool_labels = module._tool_executor_expected_labels(
        dockerfile_sha256=tool_df_sha, modules_tree_sha256=tool_mod_sha
    )
    manifest: dict[str, object] = {
        "schema_version": module.RELEASE_SCHEMA,
        "release_id": "pending",
        "package_version": package_version,
        "capability_id": "researcher-container",
        "capability_version": capability_version,
        "charter_version": capability_version,
        "runtime_version": capability_version,
        "release_identity_sha256": "pending",
        "source_identity": source_identity,
        "skill_bundle_path": "pending",
        "skill_bundle_manifest_path": "pending",
        "skill_bundle_manifest_sha256": "pending",
        "skill_bundle_tree_sha256": bundle_manifest["tree_sha256"],
        "image_tag_observational": "xinao-researcher:test",
        "image_id": image_id,
        "image_entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
        "image_labels": labels,
        "tool_image_tag_observational": "xinao-tool-executor:test",
        "tool_image_id": tool_image_id,
        "tool_image_entrypoint": list(module.TOOL_EXECUTOR_ENTRYPOINT),
        "tool_image_labels": tool_labels,
        "skill_hashes": hashes,
        "required_bootstrap_protocol": 2,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    identity_sha256 = module._sha256_bytes(
        module._canonical_bytes(module._release_identity_payload(manifest))
    )
    release_id = f"researcher-{capability_version}-{identity_sha256[:16]}"
    release_root = state / "researcher_container" / "releases" / release_id
    manifest_path = release_root / "release.json"
    manifest.update(
        {
            "release_id": release_id,
            "release_identity_sha256": identity_sha256,
            "skill_bundle_path": str(release_root / "skill-bundle"),
            "skill_bundle_manifest_path": str(release_root / "skill-bundle.manifest.json"),
            "skill_bundle_manifest_sha256": module._sha256_bytes(
                module._canonical_bytes(bundle_manifest)
            ),
        }
    )
    module._materialize_skill_bundle(release_root / "skill-bundle", source_rows, bundle_manifest)
    module._write_json_atomic(
        release_root / "skill-bundle.manifest.json", bundle_manifest, create_new=True
    )
    module._write_json_atomic(manifest_path, manifest, create_new=True)
    module._validate_release_manifest(manifest, manifest_path)
    return manifest, manifest_path


def _terminal_pointer(
    module,
    manifest: dict[str, object],
    manifest_path: Path,
    *,
    generation: int = 1,
    txn_suffix: str = "1" * 16,
    previous_verified: dict[str, object] | None = None,
    state: str = "VERIFIED",
) -> tuple[dict[str, object], dict[str, object], Path]:
    txn_id = f"xra_20260730T120000_{txn_suffix}"
    active = module._release_ref_from_manifest(manifest, manifest_path, activation_txn_id=txn_id)
    pointer = {
        "schema_version": module.CURRENT_POINTER_SCHEMA,
        "generation": generation,
        "active": active,
        "previous_verified": previous_verified,
        "switched_at": "2026-07-30T12:00:00Z",
    }
    journal_path = module._journal_path(txn_id)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    canary_path = journal_path.parent / "canary.receipt.json"
    module._write_json_atomic(canary_path, {"status": "PASS"}, create_new=True)
    journal = {
        "schema_version": module.ACTIVATION_JOURNAL_SCHEMA,
        "revision": 4,
        "txn_id": txn_id,
        "operation": "ACTIVATE",
        "state": state,
        "from": None,
        "requested_to": active,
        "to": active,
        "expected_generation": generation,
        "prepared_at": "2026-07-30T12:00:00Z",
        "updated_at": "2026-07-30T12:00:01Z",
        "switched_pointer_sha256": None,
        "canary": {
            "status": "PASS",
            "receipt_path": str(canary_path),
            "receipt_sha256": module._sha256(canary_path),
        },
        "failure_reason": None,
        "terminal_pointer_sha256": None,
    }
    module._write_json_atomic(journal_path, journal, create_new=True)
    pointer_path = module._state_paths()["pointer"]
    module._write_json_atomic(pointer_path, pointer)
    pointer_sha256 = module._sha256(pointer_path)
    journal["switched_pointer_sha256"] = pointer_sha256
    if state in module.TERMINAL_ACTIVATION_STATES:
        journal["terminal_pointer_sha256"] = pointer_sha256
    module._write_json_atomic(journal_path, journal)
    return pointer, journal, journal_path


def _install_bootstrap_fence(
    module,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> dict[str, object]:
    state_root = module._state_paths()["state_root"]
    bootstrap = _bootstrap_module()
    _runtime_path, _runtime_payload, fence = bootstrap._runtime_entry_locked(command, state_root)
    monkeypatch.setattr(module, "_BOOTSTRAP_FENCE_CACHE", None)
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(fence, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    )
    return fence


def _set_syntactic_bootstrap_fence(
    module, monkeypatch: pytest.MonkeyPatch, state_root: Path
) -> dict[str, object]:
    fence: dict[str, object] = {
        "schema_version": module.BOOTSTRAP_FENCE_SCHEMA,
        "state_root": str(state_root),
        "pointer_sha256": "1" * 64,
        "pointer_generation": 1,
        "active_txn_id": "xra_20260730T120000_" + "1" * 16,
        "pending_txn_id": None,
        "selected_release_id": "researcher-1.1.0-" + "1" * 16,
        "selected_release_manifest_sha256": "2" * 64,
        "selected_skill_bundle_tree_sha256": "3" * 64,
        "selected_runtime_sha256": "4" * 64,
    }
    monkeypatch.setattr(module, "_BOOTSTRAP_FENCE_CACHE", None)
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(fence, sort_keys=True, separators=(",", ":")),
    )
    return fence


def _canary_value(module, journal: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "xinao.researcher_activation_canary.v1",
        "status": "CANARY_READY",
        "txn_id": journal["txn_id"],
        "pointer_generation": journal["expected_generation"],
        "pointer_sha256": journal["switched_pointer_sha256"],
        "release_id": journal["to"]["release_id"],
        "release_manifest_sha256": journal["to"]["release_manifest_sha256"],
        "skill_bundle_tree_sha256": journal["to"]["skill_bundle_tree_sha256"],
        "provider_effect_verified": False,
        "completion_claim_allowed": False,
    }


def _parse_build_args(command: list[str]) -> dict[str, str]:
    args: dict[str, str] = {}
    for index, value in enumerate(command):
        if value == "--build-arg":
            key, argument = command[index + 1].split("=", 1)
            args[key] = argument
    return args


def _fake_build_environment(
    module,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dirty: bool,
    image_character: str = "e",
    donor_binary_payload: bytes = FAKE_DONOR_BINARY_PAYLOAD,
    on_before_build=None,
    fail_on: str | None = None,
) -> dict[str, object]:
    build_commands: list[list[str]] = []
    docker_commands: list[list[str]] = []
    fence_checks: list[tuple[str, object]] = []
    created_containers: list[str] = []
    removed_containers: list[str] = []
    fence = {"test_fence": "build"}
    donor_binary_sha256 = hashlib.sha256(donor_binary_payload).hexdigest()
    lock = json.loads(module.RUNTIME_LOCK_PATH.read_text(encoding="utf-8"))
    donor_id = str(lock["grok_donor_image_id"])
    donor_tag = str(lock["grok_donor_image"])
    live_containers: dict[str, dict[str, object]] = {}

    def fake_fence(command: str, *, expected=None):
        fence_checks.append((command, expected))
        assert command == "build"
        if expected is not None:
            assert expected == fence
        return dict(fence)

    def fake_run(arguments, **_kwargs):
        values = list(arguments)
        if values and values[0] == "docker":
            docker_commands.append(list(values))
        if values[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(stdout=" M source\n" if dirty else "", stderr="", returncode=0)
        if values[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout="c" * 40, stderr="", returncode=0)
        if values[:3] == ["git", "rev-parse", "HEAD^{tree}"]:
            return SimpleNamespace(stdout="d" * 40, stderr="", returncode=0)
        if values[:2] == ["docker", "create"]:
            assert "--name" in values
            assert values[values.index("--name") + 1]
            assert "--entrypoint" in values
            assert values[values.index("--entrypoint") + 1] == "/bin/true"
            assert values[-1] == donor_id
            assert donor_tag not in values
            assert "start" not in values
            assert "-v" not in values
            assert "--volume" not in values
            assert "--mount" not in values
            name = values[values.index("--name") + 1]
            assert name.startswith(module.DONOR_EXTRACT_NAME_PREFIX)
            assert name not in live_containers
            if fail_on == "create":
                raise module.XinaoError("PROCESS_FAILED", "injected create failure")
            live_containers[name] = {
                "Image": donor_id,
                "State": {"Running": False, "Status": "created"},
                "HostConfig": {"Binds": None, "Mounts": None},
                "Mounts": [],
            }
            created_containers.append(name)
            return SimpleNamespace(stdout=name + "\n", stderr="", returncode=0)
        if values[:2] == ["docker", "inspect"]:
            name = values[2]
            if fail_on == "inspect":
                raise module.XinaoError("PROCESS_FAILED", "injected inspect failure")
            assert name in live_containers
            payload = json.dumps([live_containers[name]])
            return SimpleNamespace(stdout=payload, stderr="", returncode=0)
        if values[:2] == ["docker", "cp"]:
            assert len(values) == 4
            source = values[2]
            dest = Path(values[3])
            assert source.endswith(":/usr/local/bin/grok")
            container = source.split(":", 1)[0]
            assert container in live_containers
            assert "start" not in values
            if fail_on == "cp":
                raise module.XinaoError("PROCESS_FAILED", "injected cp failure")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(donor_binary_payload)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if values[:3] == ["docker", "rm", "-f"] or values[:2] == ["docker", "rm"]:
            name = values[-1]
            live_containers.pop(name, None)
            removed_containers.append(name)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if values[:2] == ["docker", "build"]:
            if on_before_build is not None:
                on_before_build(values)
            if fail_on == "build":
                build_commands.append(values)
                raise module.XinaoError("PROCESS_FAILED", "injected build failure")
            build_commands.append(values)
            # Tool-executor formal build uses owned LF staging context (not source_root).
            if any("Dockerfile.tool-executor" in str(part) for part in values):
                assert "--file" in values
                assert "--label" in values
                context = Path(values[-1])
                assert context.is_dir(), f"tool build context missing: {context}"
                assert not (context / "skills").exists()
                assert not (context / ".git").exists()
                staged_df = context / "Dockerfile.tool-executor"
                assert staged_df.is_file()
                assert b"\r" not in staged_df.read_bytes()
                modules_root = context / module.RESEARCHER_IMAGE_CONTEXT_RELATIVE
                for relative in module.TOOL_EXECUTOR_MODULE_INVENTORY:
                    staged = modules_root / relative
                    assert staged.is_file(), f"missing staged tool module {relative}"
                    assert b"\r" not in staged.read_bytes(), f"CRLF in staged {relative}"
                return SimpleNamespace(stdout="", stderr="", returncode=0)
            args = _parse_build_args(values)
            assert "GROK_DONOR_IMAGE" not in args
            assert args.get("GROK_DONOR_IMAGE_ID") == donor_id
            assert args.get("GROK_DONOR_BINARY_SHA256") == donor_binary_sha256
            assert args.get("GROK_CLI_VERSION") == str(lock["grok_cli_version"])
            context = Path(values[-1])
            binary = context / module.DONOR_BINARY_CONTEXT_RELATIVE
            assert binary.is_file()
            assert binary.read_bytes() == donor_binary_payload
            # Live failure regression: Dockerfile COPY shadow-runtime/ requires the locked
            # cone in the owned staging context (not the repository root).
            shadow_root = context / module.SHADOW_RUNTIME_CONTEXT_RELATIVE
            assert shadow_root.is_dir(), f"missing staged shadow-runtime in {context}"
            shadow_main = shadow_root / "xinao" / "shadow_lifecycle" / "__main__.py"
            assert shadow_main.is_file(), f"missing staged shadow entrypoint in {context}"
            assert re.fullmatch(r"[0-9a-f]{64}", args.get("SHADOW_RUNTIME_TREE_SHA256", ""))
            assert re.fullmatch(r"[0-9a-f]{64}", args.get("SHADOW_RUNTIME_LOCK_SHA256", ""))
            assert re.fullmatch(
                r"[0-9a-f]{64}", args.get("RESEARCHER_IMAGE_MODULES_TREE_SHA256", "")
            )
            # Dual-profile modules must be staged (canary + episode/MCP/shell).
            modules_root = context / module.RESEARCHER_IMAGE_CONTEXT_RELATIVE
            assert modules_root.is_dir(), f"missing staged researcher modules in {context}"
            for relative in module.RESEARCHER_IMAGE_MODULE_INVENTORY:
                staged = modules_root / relative
                assert staged.is_file(), f"missing staged module {relative}"
                if relative.endswith(".sh"):
                    assert b"\r" not in staged.read_bytes(), f"CRLF in staged {relative}"
            assert not any(part == "start" for part in values)
            # No broad repository copy into the docker context.
            assert not (context / "xinao_discovery").exists()
            assert not (context / "skills").exists()
            assert not (context / ".git").exists()
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if values[:2] == ["docker", "start"]:
            raise AssertionError(f"donor container must never start: {values}")
        # Host-side fail-closed probe of the staged donor binary (never starts a container).
        if len(values) == 2 and values[1] == "version":
            binary = Path(values[0])
            assert binary.is_file(), f"missing staged grok binary for version probe: {binary}"
            # Always report the lock pin for unit-test donor stubs. Byte-level swaps remain
            # fail-closed via DONOR_BINARY_TAMPERED / pre-build hash equality; mismatched
            # real CLI versions are covered by dedicated version-mismatch tests.
            return SimpleNamespace(
                stdout=f"grok {lock['grok_cli_version']} (test-fake-binary)\n",
                stderr="",
                returncode=0,
            )
        raise AssertionError(values)

    def fake_image(_docker: str, image: str) -> dict[str, object]:
        if image in {donor_tag, donor_id}:
            return {"Id": donor_id}
        assert build_commands
        # Prefer the build command matching the requested tag when available.
        command = None
        for candidate in reversed(build_commands):
            if image in candidate:
                command = candidate
                break
        if command is None:
            command = build_commands[-1]
        if any("Dockerfile.tool-executor" in str(part) for part in command) or str(
            image
        ).startswith("xinao-tool-executor:"):
            # Recover sealed digests from --label flags on tool build.
            labels_map: dict[str, str] = {}
            i = 0
            while i < len(command):
                if command[i] == "--label" and i + 1 < len(command):
                    key, _, value = command[i + 1].partition("=")
                    labels_map[key] = value
                    i += 2
                    continue
                i += 1
            tool_df = labels_map.get("io.xinao.tool.dockerfile.sha256", "d" * 64)
            tool_mod = labels_map.get("io.xinao.tool.modules.sha256", "e" * 64)
            tool_labels = module._tool_executor_expected_labels(
                dockerfile_sha256=tool_df, modules_tree_sha256=tool_mod
            )
            tool_char = format((int(image_character, 16) + 7) % 16, "x")
            return {
                "Id": "sha256:" + tool_char * 64,
                "Config": {
                    "Labels": tool_labels,
                    "Entrypoint": list(module.TOOL_EXECUTOR_ENTRYPOINT),
                },
            }
        args = _parse_build_args(command)
        labels = {
            "io.xinao.researcher.chain": "dedicated-xinao-science",
            "io.xinao.researcher.generic-worker-route": "forbidden",
            "io.xinao.researcher.grok-donor-image-id": args["GROK_DONOR_IMAGE_ID"],
            "io.xinao.researcher.grok-donor-binary.sha256": args["GROK_DONOR_BINARY_SHA256"],
            "io.xinao.researcher.charter.sha256": args["CHARTER_SHA256"],
            "io.xinao.researcher.output-schema.sha256": args["OUTPUT_SCHEMA_SHA256"],
            "io.xinao.researcher.material-bundle-schema.sha256": args[
                "MATERIAL_BUNDLE_SCHEMA_SHA256"
            ],
            "io.xinao.researcher.runtime-lock.sha256": args["RUNTIME_LOCK_SHA256"],
            "io.xinao.researcher.skill-invoker.sha256": args["SKILL_INVOKER_SHA256"],
            "io.xinao.researcher.dockerfile.sha256": args["DOCKERFILE_SHA256"],
            "io.xinao.researcher.entrypoint.sha256": args["ENTRYPOINT_SHA256"],
            "io.xinao.researcher.source-identity.sha256": args["SOURCE_IDENTITY_SHA256"],
            "io.xinao.researcher.shadow-runtime.sha256": args["SHADOW_RUNTIME_TREE_SHA256"],
            "io.xinao.researcher.shadow-runtime-lock.sha256": args["SHADOW_RUNTIME_LOCK_SHA256"],
            "io.xinao.researcher.requested-model": args["REQUESTED_MODEL"],
            **module._dual_profile_image_labels(
                researcher_image_modules_tree_sha256=args["RESEARCHER_IMAGE_MODULES_TREE_SHA256"]
            ),
        }
        return {
            "Id": "sha256:" + image_character * 64,
            "Config": {
                "Labels": labels,
                "Entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
            },
        }

    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module, "_docker", lambda: "docker")
    monkeypatch.setattr(module, "_docker_engine_os", lambda _docker: "linux")
    monkeypatch.setattr(module, "_docker_image", fake_image)
    monkeypatch.setattr(module, "_validate_bootstrap_fence_locked", fake_fence)
    return {
        "build_commands": build_commands,
        "docker_commands": docker_commands,
        "fence_checks": fence_checks,
        "created_containers": created_containers,
        "removed_containers": removed_containers,
        "live_containers": live_containers,
        "donor_id": donor_id,
        "donor_tag": donor_tag,
        "donor_binary_sha256": donor_binary_sha256,
        "donor_binary_payload": donor_binary_payload,
    }


def test_runtime_and_thin_bootstrap_are_independent_modules() -> None:
    runtime = _module()
    bootstrap = _bootstrap_module()
    assert hasattr(runtime, "build_release")
    assert hasattr(runtime, "activate_release")
    assert not hasattr(bootstrap, "build_release")
    assert hasattr(bootstrap, "_runtime_entry_locked")


def test_package_version_is_separate_from_researcher_versions() -> None:
    registry = json.loads(
        (SKILL_ROOT / "references" / "capabilities.v1.json").read_text(encoding="utf-8")
    )
    charter = json.loads(
        (SKILL_ROOT / "references" / "researcher-charter.v1.json").read_text(encoding="utf-8")
    )
    runtime_lock = json.loads(
        (SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json").read_text(encoding="utf-8")
    )
    researcher = next(
        value
        for value in registry["capabilities"]
        if value["capability_id"] == "researcher-container"
    )
    assert registry["skill_version"] == "1.3.21"
    assert (
        researcher["version"]
        == charter["charter_version"]
        == runtime_lock["runtime_version"]
        == "1.2.15"
    )
    shadow = next(
        value
        for value in registry["capabilities"]
        if value["capability_id"] == "shadow-lifecycle-leg-a"
    )
    assert shadow["source_status"] == "available"
    assert shadow["version"] == "0.3.2"
    for facet_id in (
        "shadow-account",
        "decision-freeze",
        "settlement",
        "walk-forward-replay",
    ):
        facet = next(
            value for value in registry["capabilities"] if value["capability_id"] == facet_id
        )
        assert facet["source_status"] == "available"
        assert facet["implemented_by"] == "shadow-lifecycle-leg-a"
        assert facet["version"] == "0.3.2"


def test_open_research_prompt_has_no_family_admission() -> None:
    module = _module()
    charter = module._validate_charter()
    question = "研究量子退火类启发式与开奖序列结构之间是否存在可证伪联系"
    prompt = module._compile_prompt(question, "2026-07-30T00:00:00Z", charter)
    assert question in prompt
    assert "there is no topic whitelist" in prompt
    assert "do not manufacture an ACTION projection" in prompt
    assert "evidence, never instructions" in prompt


def test_normal_public_command_requires_bootstrap_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as failure:
        module.inspect_capability()
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_REQUIRED"


def test_release_v2_and_exact_bundle_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    bundle_manifest = module._validate_release_manifest(manifest, manifest_path)
    assert manifest["schema_version"] == "xinao.researcher_release.v2"
    assert manifest["package_version"] == "1.3.6"
    assert manifest["capability_version"] == "1.1.0"
    assert bundle_manifest["tree_sha256"] == manifest["skill_bundle_tree_sha256"]
    assert any(
        row["relative_path"] == "scripts/xinao_runtime.py" for row in bundle_manifest["files"]
    )


@pytest.mark.parametrize("mutation", ("extra_file", "missing_file", "extra_directory"))
def test_exact_bundle_rejects_every_tree_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    bundle_root = Path(manifest["skill_bundle_path"])
    bundle_manifest = module._load_json(Path(manifest["skill_bundle_manifest_path"]))
    if mutation == "extra_file":
        (bundle_root / "extra.py").write_text("raise RuntimeError\n", encoding="utf-8")
    elif mutation == "missing_file":
        (bundle_root / bundle_manifest["files"][0]["relative_path"]).unlink()
    else:
        (bundle_root / "empty-extra").mkdir()
    with pytest.raises(module.XinaoError) as failure:
        module._validate_release_manifest(manifest, manifest_path)
    assert failure.value.reason_code in {
        "SKILL_BUNDLE_INVENTORY_MISMATCH",
        "SKILL_BUNDLE_ENTRY_IDENTITY_MISMATCH",
    }


def test_bundle_reparse_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    manifest, _manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    bundle_root = Path(manifest["skill_bundle_path"])
    target = bundle_root / "scripts" / "xinao_runtime.py"
    original = module._is_reparse
    monkeypatch.setattr(module, "_is_reparse", lambda path: path == target or original(path))
    with pytest.raises(module.XinaoError) as failure:
        module._verify_skill_bundle(
            bundle_root, module._load_json(Path(manifest["skill_bundle_manifest_path"]))
        )
    assert failure.value.reason_code == "SKILL_BUNDLE_REPARSE_FORBIDDEN"


def test_runtime_activation_lock_is_safely_created_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock_path = module._state_paths()["lock"]
    lock_path.unlink()
    with module._activation_lock():
        observed = os.lstat(lock_path)
        assert observed.st_nlink == 1
        assert observed.st_size >= 1
    assert lock_path.is_file()


def test_runtime_activation_lock_rejects_hardlink_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock_path = module._state_paths()["lock"]
    alias = tmp_path / "activation-lock-alias"
    try:
        os.link(lock_path, alias)
    except OSError:
        pytest.skip("hardlinks unavailable")
    with pytest.raises(module.XinaoError) as failure:
        with module._activation_lock():
            pytest.fail("hardlinked lock must not be acquired")
    assert failure.value.reason_code == "ACTIVATION_LOCK_INVALID"


def test_runtime_activation_lock_detects_path_identity_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock_path = module._state_paths()["lock"]
    replacement = tmp_path / "replacement-lock"
    replacement.write_bytes(b"\0")
    original_lstat = os.lstat
    lock_lstat_calls = 0

    def replaced_lstat(path):
        nonlocal lock_lstat_calls
        if module._paths_equal(Path(path), lock_path):
            lock_lstat_calls += 1
            if lock_lstat_calls >= 3:
                return original_lstat(replacement)
        return original_lstat(path)

    monkeypatch.setattr(module.os, "lstat", replaced_lstat)
    with pytest.raises(module.XinaoError) as failure:
        with module._activation_lock():
            pytest.fail("replaced lock must not be acquired")
    assert failure.value.reason_code == "ACTIVATION_LOCK_CHANGED"
    assert lock_lstat_calls >= 3


def test_dockerfile_has_no_donor_from_or_raw_image_id_stage() -> None:
    """Real-failure regression: raw local image Id in FROM is unbuildable under BuildKit."""
    dockerfile = (ROOT / "docker" / "xinao-researcher" / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG GROK_DONOR_IMAGE=" not in dockerfile
    assert "ARG GROK_DONOR_IMAGE\n" not in dockerfile
    assert "AS grok_donor" not in dockerfile
    assert "COPY --from=grok_donor" not in dockerfile
    assert re.search(r"^FROM\s+\$\{?GROK_DONOR", dockerfile, flags=re.MULTILINE) is None
    assert re.search(r"^FROM\s+sha256:", dockerfile, flags=re.MULTILINE) is None
    assert "COPY donor-artifacts/grok" in dockerfile
    assert "GROK_DONOR_BINARY_SHA256" in dockerfile
    assert "ARG GROK_DONOR_IMAGE_ID" in dockerfile
    assert "ARG GROK_CLI_VERSION" in dockerfile
    assert 'test "$parsed" = "${GROK_CLI_VERSION}"' in dockerfile
    assert "io.xinao.researcher.grok-donor-binary.sha256" in dockerfile


def test_require_staged_grok_cli_version_fail_closed(tmp_path: Path) -> None:
    module = _module()
    binary = tmp_path / "grok"
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o755)

    def fake_run(arguments, **_kwargs):
        values = list(arguments)
        assert values == [str(binary), "version"]
        return SimpleNamespace(stdout="grok 0.2.112 (deadbeef)\n", stderr="", returncode=0)

    module._run = fake_run  # type: ignore[method-assign]
    assert module._parse_grok_cli_version("grok 0.2.117 (f1c0609308)") == "0.2.117"
    with pytest.raises(module.XinaoError) as failure:
        module._require_staged_grok_cli_version(binary, expected_version="0.2.117")
    assert failure.value.reason_code == "GROK_CLI_VERSION_MISMATCH"
    assert "0.2.112" in failure.value.detail

    def ok_run(arguments, **_kwargs):
        return SimpleNamespace(stdout="grok 0.2.117 (f1c0609308)\n", stderr="", returncode=0)

    module._run = ok_run  # type: ignore[method-assign]
    assert module._require_staged_grok_cli_version(binary, expected_version="0.2.117") == "0.2.117"


def test_probe_grok_binary_version_process_start_failed_elf_docker_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wave106/108: Windows cannot exec Linux donor ELF; fall back to Docker-mount probe.

    Existing fail-closed version tests only exercise the native-success path. This test
    executes the PROCESS_START_FAILED → ELF magic → docker_exec_image_id mount path.
    """
    module = _module()
    binary = tmp_path / "grok"
    # Minimal Linux ELF magic so _linux_elf_magic is true; body is not executed natively.
    binary.write_bytes(b"\x7fELF" + b"\x00" * 12)
    binary.chmod(0o755)
    donor_image = "sha256:" + ("ab" * 32)
    calls: list[list[str]] = []

    def fake_run(arguments, **_kwargs):
        values = [str(v) for v in arguments]
        calls.append(values)
        # Native probe fails like WinError 193 for any direct binary path.
        if len(values) == 2 and values[1] == "version" and values[0].endswith("grok"):
            raise module.XinaoError(
                "PROCESS_START_FAILED",
                f"command={values[0]}: [WinError 193] %1 is not a valid Win32 application",
            )
        # Docker-mount fallback of the same staged bytes.
        if values[:2] == [module._docker(), "run"] and "--entrypoint" in values:
            entry_idx = values.index("--entrypoint")
            assert values[entry_idx + 1] == "/xinao-donor-probe/grok"
            assert donor_image in values
            assert any("xinao-donor-probe" in part for part in values)
            assert values[-1] == "version"
            return SimpleNamespace(
                stdout="grok 0.2.117 (f1c0609308)\n",
                stderr="",
                returncode=0,
            )
        raise AssertionError(f"unexpected _run arguments: {values}")

    monkeypatch.setattr(module, "_run", fake_run)
    text = module._probe_grok_binary_version_text(binary, docker_exec_image_id=donor_image)
    assert text.startswith("grok 0.2.117")
    assert any(len(c) == 2 and c[1] == "version" for c in calls)
    assert any("run" in c and "--entrypoint" in c for c in calls)
    assert (
        module._require_staged_grok_cli_version(
            binary, expected_version="0.2.117", docker_exec_image_id=donor_image
        )
        == "0.2.117"
    )

    # Non-ELF + PROCESS_START_FAILED must not claim Docker mount fallback.
    non_elf = tmp_path / "not-elf-grok"
    non_elf.write_bytes(b"MZ-not-elf")
    with pytest.raises(module.XinaoError) as non_elf_fail:
        module._probe_grok_binary_version_text(non_elf, docker_exec_image_id=donor_image)
    assert non_elf_fail.value.reason_code == "PROCESS_START_FAILED"

    # ELF without docker image id stays fail-closed with host-incompatible code.
    with pytest.raises(module.XinaoError) as no_docker:
        module._probe_grok_binary_version_text(binary, docker_exec_image_id=None)
    assert no_docker.value.reason_code == "GROK_CLI_VERSION_PROBE_HOST_INCOMPATIBLE"


def test_build_rejects_donor_cli_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=True)
    original_run = module._run

    def mismatch_version_run(arguments, **kwargs):
        values = list(arguments)
        if len(values) == 2 and values[1] == "version":
            return SimpleNamespace(
                stdout="grok 0.2.112 (donor-mismatch)\n",
                stderr="",
                returncode=0,
            )
        return original_run(arguments, **kwargs)

    monkeypatch.setattr(module, "_run", mismatch_version_run)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=True)
    assert failure.value.reason_code == "GROK_CLI_VERSION_MISMATCH"
    assert env["build_commands"] == []


def test_build_is_candidate_only_and_passes_complete_image_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=True)
    build_commands = env["build_commands"]
    fence_checks = env["fence_checks"]
    donor_id = env["donor_id"]
    donor_tag = env["donor_tag"]
    donor_binary_sha256 = env["donor_binary_sha256"]
    receipt = module.build_release(ROOT, allow_dirty=True)
    assert receipt["status"] == "CANDIDATE_BUILT"
    assert receipt["package_version"] == "1.3.21"
    assert receipt["capability_version"] == "1.2.15"
    assert receipt.get("tool_image_id")
    assert str(receipt["tool_image_id"]).startswith("sha256:")
    assert receipt["source_dirty"] is True
    assert receipt["activated"] is False
    assert not module._state_paths()["pointer"].exists()
    build = build_commands[0]
    joined = "\n".join(build)
    for key in (
        "DOCKERFILE_SHA256",
        "ENTRYPOINT_SHA256",
        "SOURCE_IDENTITY_SHA256",
        "SHADOW_RUNTIME_TREE_SHA256",
        "SHADOW_RUNTIME_LOCK_SHA256",
        "REQUESTED_MODEL=grok-4.5",
        f"GROK_DONOR_IMAGE_ID={donor_id}",
        f"GROK_DONOR_BINARY_SHA256={donor_binary_sha256}",
        "GROK_CLI_VERSION=0.2.117",
    ):
        assert key in joined
    assert "GROK_DONOR_IMAGE=" not in joined
    assert donor_tag not in joined
    assert str(ROOT) not in build[-1]
    assert (Path(build[-1]) / module.DONOR_BINARY_CONTEXT_RELATIVE).name == "grok"
    # Build context is cleaned after success; physical staging is asserted at docker-build
    # time inside _fake_build_environment. Seal identities still bind the staged cone.
    assert "SHADOW_RUNTIME_TREE_SHA256=" in joined
    assert "SHADOW_RUNTIME_LOCK_SHA256=" in joined
    assert receipt["grok_cli_version"] == "0.2.117"
    assert receipt["grok_donor_image_id"] == donor_id
    assert receipt["grok_donor_binary_sha256"] == donor_binary_sha256
    manifest = module._load_json(Path(receipt["release_manifest_path"]))
    module._validate_release_manifest(manifest, Path(receipt["release_manifest_path"]))
    assert manifest["source_identity"]["grok_donor_image_id"] == donor_id
    assert manifest["source_identity"]["grok_donor_binary_sha256"] == donor_binary_sha256
    assert re.fullmatch(
        r"[0-9a-f]{64}", manifest["source_identity"]["tool_executor_dockerfile_sha256"]
    )
    assert re.fullmatch(
        r"[0-9a-f]{64}", manifest["source_identity"]["tool_executor_modules_tree_sha256"]
    )
    assert manifest["tool_image_id"].startswith("sha256:")
    assert manifest["tool_image_entrypoint"] == list(module.TOOL_EXECUTOR_ENTRYPOINT)
    assert manifest["tool_image_labels"]["io.xinao.researcher.role"] == "tool_executor"
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["source_identity"]["shadow_runtime_tree_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["source_identity"]["shadow_runtime_lock_sha256"])
    assert manifest["image_labels"]["io.xinao.researcher.grok-donor-image-id"] == donor_id
    assert (
        manifest["image_labels"]["io.xinao.researcher.grok-donor-binary.sha256"]
        == donor_binary_sha256
    )
    assert (
        manifest["image_labels"]["io.xinao.researcher.shadow-runtime.sha256"]
        == manifest["source_identity"]["shadow_runtime_tree_sha256"]
    )
    assert (
        manifest["image_labels"]["io.xinao.researcher.shadow-runtime-lock.sha256"]
        == manifest["source_identity"]["shadow_runtime_lock_sha256"]
    )
    assert fence_checks == [
        ("build", None),
        ("build", {"test_fence": "build"}),
        ("build", {"test_fence": "build"}),
        ("build", {"test_fence": "build"}),
    ]
    # Exact create/inspect/cp shape; never start; cleanup removed the extract container.
    docker_commands = env["docker_commands"]
    assert any(cmd[:2] == ["docker", "create"] for cmd in docker_commands)
    assert any(cmd[:2] == ["docker", "inspect"] for cmd in docker_commands)
    assert any(cmd[:2] == ["docker", "cp"] for cmd in docker_commands)
    assert any(cmd[:3] == ["docker", "rm", "-f"] for cmd in docker_commands)
    assert not any(cmd[:2] == ["docker", "start"] for cmd in docker_commands)
    assert env["created_containers"]
    assert set(env["created_containers"]).issubset(set(env["removed_containers"]))
    assert env["live_containers"] == {}
    assert not any(
        path.name.startswith(module.DONOR_STAGING_DIR_PREFIX)
        for path in module._state_paths()["capability_root"].iterdir()
    )


def test_build_extract_pins_binary_against_tag_retarget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SP-B-001: tag retarget after first inspect cannot change staged donor bytes."""
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock = json.loads(module.RUNTIME_LOCK_PATH.read_text(encoding="utf-8"))
    donor_tag = str(lock["grok_donor_image"])
    pinned_id = str(lock["grok_donor_image_id"])
    retargeted_id = "sha256:" + "9" * 64
    assert retargeted_id != pinned_id

    donor_tag_inspects = 0
    tag_retargeted = False

    def on_before_build(values: list[str]) -> None:
        nonlocal tag_retargeted
        # Dual-image generation builds tool-executor second; only assert donor pins on transport.
        if any("Dockerfile.tool-executor" in str(part) for part in values):
            return
        tag_retargeted = True
        args = _parse_build_args(values)
        assert "GROK_DONOR_IMAGE" not in args
        assert args["GROK_DONOR_IMAGE_ID"] == pinned_id
        assert args["GROK_DONOR_BINARY_SHA256"] == FAKE_DONOR_BINARY_SHA256
        context = Path(values[-1])
        assert (context / module.DONOR_BINARY_CONTEXT_RELATIVE).read_bytes() == (
            FAKE_DONOR_BINARY_PAYLOAD
        )

    env = _fake_build_environment(module, monkeypatch, dirty=False, on_before_build=on_before_build)
    original_image = module._docker_image

    def retarget_aware_image(_docker: str, image: str) -> dict[str, object]:
        nonlocal donor_tag_inspects
        if image == donor_tag:
            donor_tag_inspects += 1
            if tag_retargeted or donor_tag_inspects > 1:
                return {"Id": retargeted_id}
            return {"Id": pinned_id}
        if image == pinned_id:
            return {"Id": pinned_id}
        if image == retargeted_id:
            return {"Id": retargeted_id}
        return original_image(_docker, image)

    monkeypatch.setattr(module, "_docker_image", retarget_aware_image)

    receipt = module.build_release(ROOT, allow_dirty=False)
    assert receipt["status"] == "CANDIDATE_BUILT"
    assert tag_retargeted is True
    assert donor_tag_inspects == 1
    assert len(env["build_commands"]) == 2
    assert any(
        "Dockerfile.tool-executor" in str(part) for cmd in env["build_commands"] for part in cmd
    )
    assert module._docker_image("docker", donor_tag)["Id"] == retargeted_id
    assert module._docker_image("docker", pinned_id)["Id"] == pinned_id
    manifest = module._load_json(Path(receipt["release_manifest_path"]))
    module._validate_release_manifest(manifest, Path(receipt["release_manifest_path"]))
    assert manifest["source_identity"]["grok_donor_image_id"] == pinned_id
    assert manifest["source_identity"]["grok_donor_binary_sha256"] == FAKE_DONOR_BINARY_SHA256
    assert manifest["image_labels"]["io.xinao.researcher.grok-donor-image-id"] == pinned_id
    assert (
        manifest["image_labels"]["io.xinao.researcher.grok-donor-binary.sha256"]
        == FAKE_DONOR_BINARY_SHA256
    )
    assert manifest["source_identity"]["grok_donor_image_id"] != retargeted_id


def test_build_detects_staged_binary_tamper_before_docker_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=False)
    original_prepare = module._prepare_donor_binary_staging

    def prepare_then_tamper(docker: str, *, donor_image_id: str, entrypoint_path: Path):
        result = original_prepare(
            docker, donor_image_id=donor_image_id, entrypoint_path=entrypoint_path
        )
        _binary_sha256, _staging_root, build_context, _container_name = result
        binary = build_context / module.DONOR_BINARY_CONTEXT_RELATIVE
        binary.write_bytes(b"tampered-donor-binary\n")
        return result

    monkeypatch.setattr(module, "_prepare_donor_binary_staging", prepare_then_tamper)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "DONOR_BINARY_TAMPERED"
    assert env["live_containers"] == {}
    assert not any(
        path.name.startswith(module.DONOR_STAGING_DIR_PREFIX)
        for path in module._state_paths()["capability_root"].iterdir()
        if path.is_dir()
    )


def test_build_rejects_non_regular_staged_donor_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=False)
    original_run = module._run

    def symlink_cp(arguments, **kwargs):
        values = list(arguments)
        if values[:2] == ["docker", "cp"]:
            dest = Path(values[3])
            dest.parent.mkdir(parents=True, exist_ok=True)
            target = dest.parent / "link-target"
            target.write_bytes(FAKE_DONOR_BINARY_PAYLOAD)
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            dest.symlink_to(target)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        return original_run(arguments, **kwargs)

    monkeypatch.setattr(module, "_run", symlink_cp)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "DONOR_BINARY_INVALID"
    assert env["live_containers"] == {}


@pytest.mark.parametrize("fail_on", ("create", "inspect", "cp", "build"))
def test_build_donor_extract_cleanup_on_every_failure_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_on: str
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=False, fail_on=fail_on)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "PROCESS_FAILED"
    assert env["live_containers"] == {}
    capability_root = module._state_paths()["capability_root"]
    leftovers = [
        path
        for path in capability_root.iterdir()
        if path.name.startswith(module.DONOR_STAGING_DIR_PREFIX)
    ]
    assert leftovers == []
    if fail_on != "create":
        assert env["created_containers"]
        assert set(env["created_containers"]).issubset(set(env["removed_containers"]))


def test_build_concurrent_extract_identities_are_unique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    names: list[str] = []
    staging_roots: list[Path] = []

    def capture_prepare(docker: str, *, donor_image_id: str, entrypoint_path: Path):
        result = original_prepare(
            docker, donor_image_id=donor_image_id, entrypoint_path=entrypoint_path
        )
        binary_sha256, staging_root, build_context, container_name = result
        names.append(container_name)
        staging_roots.append(staging_root)
        return result

    env = _fake_build_environment(module, monkeypatch, dirty=False)
    original_prepare = module._prepare_donor_binary_staging
    monkeypatch.setattr(module, "_prepare_donor_binary_staging", capture_prepare)
    first = module.build_release(ROOT, allow_dirty=False)
    second = module.build_release(ROOT, allow_dirty=False)
    assert first["status"] == second["status"] == "CANDIDATE_BUILT"
    assert len(names) == 2
    assert names[0] != names[1]
    assert staging_roots[0] != staging_roots[1]
    assert all(name.startswith(module.DONOR_EXTRACT_NAME_PREFIX) for name in names)
    assert all(root.name.startswith(module.DONOR_STAGING_DIR_PREFIX) for root in staging_roots)
    assert env["live_containers"] == {}


def test_build_parser_has_no_promote_flag(capsys: pytest.CaptureFixture[str]) -> None:
    module = _module()
    code = module.main(["build", "--source-root", str(ROOT), "--promote"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["reason_codes"] == ["INVOCATION_ARGUMENTS_INVALID"]


def test_same_semver_different_content_is_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        package_version="1.3.21",
        capability_version="1.2.15",
    )
    _fake_build_environment(module, monkeypatch, dirty=False, image_character="f")
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "SEMVER_CONTENT_COLLISION"
    assert failure.value.detail == "package=1.3.21 capability=1.2.15"


def test_package_version_bump_can_reuse_researcher_capability_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    old, old_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        package_version="1.3.1",
        capability_version="1.2.1",
    )
    old_bytes = old_path.read_bytes()
    _fake_build_environment(module, monkeypatch, dirty=False, image_character="f")

    receipt = module.build_release(ROOT, allow_dirty=False)
    new_path = Path(receipt["release_manifest_path"])
    new = module._load_json(new_path)

    assert receipt["status"] == "CANDIDATE_BUILT"
    assert receipt["package_version"] == "1.3.21"
    assert receipt["capability_version"] == "1.2.15"
    assert new["release_id"] != old["release_id"]
    assert new["package_version"] == "1.3.21"
    assert new["capability_version"] == "1.2.15"
    assert old_path.read_bytes() == old_bytes


def test_forward_upgrade_target_build_accepts_package_only_bump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    old, old_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        package_version="1.3.1",
        capability_version="1.2.1",
    )
    old_bytes = old_path.read_bytes()
    _terminal_pointer(
        module,
        old,
        old_path,
        generation=4,
        txn_suffix="9" * 16,
        previous_verified=None,
    )
    monkeypatch.setattr(module, "_migration_source_root", lambda: ROOT)
    _fake_build_environment(module, monkeypatch, dirty=False, image_character="f")

    prepared = module._prepare_forward_upgrade_target()

    assert prepared is not None
    new, new_path = prepared
    assert new_path.is_file()
    assert new["release_id"] != old["release_id"]
    assert new["package_version"] == "1.3.21"
    assert new["capability_version"] == "1.2.15"
    assert old_path.read_bytes() == old_bytes


@pytest.mark.parametrize(
    ("failure_call", "expected_build_count"),
    ((2, 0), (3, 1)),
)
def test_build_fence_blocks_effect_or_release_seal_at_the_matching_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_call: int,
    expected_build_count: int,
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=False)
    build_commands = env["build_commands"]
    fence = {"test_fence": "build"}
    calls = 0

    def fail_at_boundary(command: str, *, expected=None):
        nonlocal calls
        calls += 1
        assert command == "build"
        if calls == failure_call:
            raise module.XinaoError("BOOTSTRAP_FENCE_STATE_DRIFT", "injected")
        if expected is not None:
            assert expected == fence
        return dict(fence)

    monkeypatch.setattr(module, "_validate_bootstrap_fence_locked", fail_at_boundary)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"
    assert len(build_commands) == expected_build_count
    assert not module._state_paths()["release_root"].exists()
    # Fence failure after extract still cleans temporary donor staging/container.
    assert env["live_containers"] == {}
    capability_root = module._state_paths()["capability_root"]
    assert not any(
        path.name.startswith(module.DONOR_STAGING_DIR_PREFIX) for path in capability_root.iterdir()
    )


def test_legacy_pointer_fails_before_any_activation_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, _manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    pointer_path = module._state_paths()["pointer"]
    legacy = {
        "schema_version": "xinao.researcher_current_pointer.v1",
        "release_id": manifest["release_id"],
    }
    module._write_json_atomic(pointer_path, legacy)
    before = pointer_path.read_bytes()
    _set_syntactic_bootstrap_fence(module, monkeypatch, tmp_path / "state")
    with pytest.raises(module.XinaoError) as failure:
        module.activate_release(str(manifest["release_id"]))
    assert failure.value.reason_code == "BOOTSTRAP_MIGRATION_REQUIRED"
    assert pointer_path.read_bytes() == before
    assert not module._state_paths()["transaction_root"].exists()


def test_dirty_candidate_never_activates_or_changes_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    clean, clean_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, clean, clean_path)
    dirty, _dirty_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="b",
        dirty=True,
    )
    pointer_path = module._state_paths()["pointer"]
    before = pointer_path.read_bytes()
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(dirty["release_id"])]
    )
    with pytest.raises(module.XinaoError) as failure:
        module.activate_release(str(dirty["release_id"]))
    assert failure.value.reason_code == "DIRTY_RELEASE_ACTIVATION_FORBIDDEN"
    assert pointer_path.read_bytes() == before
    assert module._pending_journals() == []


def test_activation_release_validation_excludes_egress_and_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, _manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    charter = module._validate_charter()
    runtime_lock = module._load_json(module.RUNTIME_LOCK_PATH)
    monkeypatch.setattr(
        module,
        "_validate_release_source_identity",
        lambda _release: (charter, runtime_lock),
    )
    monkeypatch.setattr(
        module,
        "_require_host_egress_boundary",
        lambda *_args, **_kwargs: pytest.fail("activation must not require provider egress"),
    )
    monkeypatch.setattr(module, "DEFAULT_AUTH_PATH", tmp_path / "missing-auth.json")
    monkeypatch.setattr(module, "_docker", lambda: "docker")
    monkeypatch.setattr(module, "_docker_engine_os", lambda _docker: "linux")

    def _dual_image(_docker, image):
        if image == manifest["tool_image_id"]:
            return {
                "Id": manifest["tool_image_id"],
                "Config": {
                    "Labels": manifest["tool_image_labels"],
                    "Entrypoint": manifest["tool_image_entrypoint"],
                },
            }
        return {
            "Id": manifest["image_id"],
            "Config": {
                "Labels": manifest["image_labels"],
                "Entrypoint": manifest["image_entrypoint"],
            },
        }

    monkeypatch.setattr(module, "_docker_image", _dual_image)

    docker, observed_charter = module._validate_release_for_activation(manifest)

    assert docker == "docker"
    assert observed_charter == charter


@pytest.mark.parametrize(
    ("field", "reason_code"),
    (
        ("label", "IMAGE_LABEL_IDENTITY_MISMATCH"),
        ("entrypoint", "IMAGE_ENTRYPOINT_IDENTITY_MISMATCH"),
    ),
)
def test_activation_release_validation_rejects_image_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    reason_code: str,
) -> None:
    module = _module()
    manifest, _manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    charter = module._validate_charter()
    runtime_lock = module._load_json(module.RUNTIME_LOCK_PATH)
    observed_labels = dict(manifest["image_labels"])
    observed_entrypoint = list(manifest["image_entrypoint"])
    if field == "label":
        observed_labels["io.xinao.researcher.chain"] = "tampered"
    else:
        observed_entrypoint[-1] = "/tmp/tampered.py"
    monkeypatch.setattr(
        module,
        "_validate_release_source_identity",
        lambda _release: (charter, runtime_lock),
    )
    monkeypatch.setattr(module, "_docker", lambda: "docker")
    monkeypatch.setattr(module, "_docker_engine_os", lambda _docker: "linux")

    def _dual_image(_docker, image):
        if image == manifest["tool_image_id"]:
            return {
                "Id": manifest["tool_image_id"],
                "Config": {
                    "Labels": manifest["tool_image_labels"],
                    "Entrypoint": manifest["tool_image_entrypoint"],
                },
            }
        return {
            "Id": manifest["image_id"],
            "Config": {
                "Labels": observed_labels,
                "Entrypoint": observed_entrypoint,
            },
        }

    monkeypatch.setattr(module, "_docker_image", _dual_image)

    with pytest.raises(module.XinaoError) as failure:
        module._validate_release_for_activation(manifest)

    assert failure.value.reason_code == reason_code


def test_activation_canary_uses_activation_gate_not_invoke_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    txn_id = "xra_20260730T120000_" + "a" * 16
    release = {
        "release_id": "researcher-1.1.0-" + "b" * 16,
        "skill_bundle_tree_sha256": "c" * 64,
    }
    context = {
        "journal": {"txn_id": txn_id, "state": "CANARY_STARTED"},
        "pointer": {
            "generation": 2,
            "active": {"release_manifest_sha256": "d" * 64},
        },
        "pointer_sha256": "e" * 64,
        "release": release,
    }
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(module, "_load_current_context", lambda **_kwargs: context)
    monkeypatch.setattr(
        module,
        "_validate_release_for_activation",
        lambda value: calls.append(value) or ("docker", {}),
    )
    monkeypatch.setattr(
        module,
        "_validate_release_for_invoke",
        lambda _value: pytest.fail("activation canary must not require invoke readiness"),
    )

    receipt = module._activation_canary(txn_id)

    assert calls == [release]
    assert receipt["status"] == "CANARY_READY"
    assert receipt["provider_effect_verified"] is False


def test_activation_canary_failure_surfaces_child_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    txn_id = "xra_20260730T120000_" + "f" * 16
    journal = {
        "txn_id": txn_id,
        "to": {"release_manifest_path": str(tmp_path / "release.json")},
    }
    child = module._error_envelope(module.XinaoError("IMAGE_IDENTITY_MISMATCH", "candidate image"))
    monkeypatch.setattr(
        module,
        "_run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=2,
            stdout=json.dumps(child),
            stderr="",
        ),
    )
    monkeypatch.setattr(module, "_verify_stable_installed_launcher", lambda _journal: {})

    with pytest.raises(module.XinaoError) as failure:
        module._run_activation_canary(journal)

    assert failure.value.reason_code == "ACTIVATION_CANARY_FAILED"
    assert "child_reason=IMAGE_IDENTITY_MISMATCH" in failure.value.detail


def _materialize_installed_from_release(
    module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: dict[str, object]
) -> Path:
    installed = tmp_path / "installed-skill-aligned"
    if installed.exists():
        for path in sorted(installed.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    bundle_root = Path(str(manifest["skill_bundle_path"]))
    files, directories = module._strict_plain_tree(
        bundle_root, reason_code="INSTALL_PROJECTION_TARGET_INVALID"
    )
    installed.mkdir(parents=True, exist_ok=False)
    for relative in sorted(directories):
        (installed / relative).mkdir(parents=True, exist_ok=True)
    for relative, payload in files.items():
        destination = installed / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    return installed


def test_inspect_still_reports_missing_egress_after_activation_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _materialize_installed_from_release(module, tmp_path, monkeypatch, manifest)
    _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    # Image identity is validated independently so shadow can still report live
    # capability when researcher egress is absent, provided installed projection is aligned.
    monkeypatch.setattr(module, "_validate_release_image_identity", lambda _release: "docker")
    monkeypatch.setattr(
        module,
        "_validate_release_for_invoke",
        lambda _release: (_ for _ in ()).throw(
            module.XinaoError("EGRESS_LIVE_SEAL_MISSING", "expected after install")
        ),
    )

    receipt = module.inspect_capability()

    assert receipt["runtime_status"] == "EGRESS_BOUNDARY_UNAVAILABLE"
    assert receipt["runtime_reason_code"] == "EGRESS_LIVE_SEAL_MISSING"
    assert receipt["provider_effect_verified"] is False
    assert receipt["installed_projection"]["status"] == "ALIGNED"
    assert receipt["shadow"]["runtime_status"] == "AVAILABLE"
    assert receipt["shadow"]["completion_claim_allowed"] is False


def test_activate_verifies_canary_and_keeps_full_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    first_pointer, _journal, _path = _terminal_pointer(module, first, first_path)
    second, _second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"second"
    )
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda journal: _canary_value(module, journal)
    )
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(second["release_id"])]
    )
    receipt = module.activate_release(str(second["release_id"]))
    pointer = module._load_json(module._state_paths()["pointer"])
    journal = module._load_json(Path(receipt["activation_journal_path"]))
    assert receipt["status"] == "VERIFIED"
    assert pointer["generation"] == 2
    assert pointer["active"]["release_id"] == second["release_id"]
    assert pointer["previous_verified"] == first_pointer["active"]
    assert journal["state"] == "VERIFIED"
    assert journal["txn_id"] == pointer["active"]["activation_txn_id"]
    assert journal["terminal_pointer_sha256"] == module._sha256(module._state_paths()["pointer"])
    assert module._load_current_context()["release"]["release_id"] == second["release_id"]


def test_failed_activation_rolls_back_with_new_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, _second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"second"
    )
    calls: list[str] = []

    def canary(journal):
        release_id = journal["to"]["release_id"]
        calls.append(release_id)
        if release_id == second["release_id"]:
            raise module.XinaoError("ACTIVATION_CANARY_FAILED", "injected")
        return _canary_value(module, journal)

    monkeypatch.setattr(module, "_run_activation_canary", canary)
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(second["release_id"])]
    )
    receipt = module.activate_release(str(second["release_id"]))
    pointer = module._load_json(module._state_paths()["pointer"])
    journal = module._load_json(Path(receipt["activation_journal_path"]))
    assert receipt["status"] == "ROLLED_BACK"
    assert pointer["generation"] == 3
    assert pointer["active"]["release_id"] == first["release_id"]
    assert journal["state"] == "ROLLED_BACK"
    assert calls == [second["release_id"], first["release_id"]]
    assert module._load_current_context()["release"]["release_id"] == first["release_id"]


@pytest.mark.parametrize("crash_state", ("PREPARED", "POINTER_SWITCHED", "CANARY_STARTED"))
def test_recover_converges_each_activation_crash_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_state: str,
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"recover"
    )
    with module._activation_lock():
        current = module._load_current_context()
        journal, journal_path = module._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
        if crash_state != "PREPARED":
            journal, _pointer, _sha = module._switch_prepared_pointer(journal, journal_path)
        if crash_state == "CANARY_STARTED":
            journal = module._journal_transition(journal_path, journal, "CANARY_STARTED")
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    _install_bootstrap_fence(module, monkeypatch, ["recover", "--txn-id", str(journal["txn_id"])])
    receipt = module.recover_release(str(journal["txn_id"]))
    assert receipt["status"] == "VERIFIED"
    assert module._load_current_context()["release"]["release_id"] == second["release_id"]
    assert module._load_json(journal_path)["state"] == "VERIFIED"


def test_recover_explicit_transaction_must_match_fenced_pending_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"recover-fence"
    )
    with module._activation_lock():
        current = module._load_current_context()
        journal, journal_path = module._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
    _install_bootstrap_fence(module, monkeypatch, ["recover", "--txn-id", str(journal["txn_id"])])
    pointer_path = module._state_paths()["pointer"]
    pointer_before = pointer_path.read_bytes()
    journal_before = journal_path.read_bytes()
    mismatched_txn_id = "xra_20260730T120001_" + "f" * 16
    with pytest.raises(module.XinaoError) as failure:
        module.recover_release(mismatched_txn_id)
    assert failure.value.reason_code == "RECOVERY_TRANSACTION_FENCE_MISMATCH"
    assert pointer_path.read_bytes() == pointer_before
    assert journal_path.read_bytes() == journal_before


def test_rollback_requires_complete_previous_verified_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, first, first_path)
    pointer_path = module._state_paths()["pointer"]
    before = pointer_path.read_bytes()
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "ROLLBACK_MATERIAL_ABSENT"
    assert pointer_path.read_bytes() == before


def test_rollback_switches_to_full_previous_and_increments_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, _second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"second"
    )
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(second["release_id"])]
    )
    module.activate_release(str(second["release_id"]))
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    receipt = module.rollback_release()
    pointer = module._load_json(module._state_paths()["pointer"])
    assert receipt["status"] == "ROLLED_BACK"
    assert pointer["generation"] == 3
    assert pointer["active"]["release_id"] == first["release_id"]
    assert pointer["previous_verified"]["release_id"] == second["release_id"]
    assert module._load_current_context()["journal"]["state"] == "ROLLED_BACK"


def test_pending_runtime_inspection_reports_recovery_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"pending-inspection"
    )
    with module._activation_lock():
        current = module._load_current_context()
        module._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
    _install_bootstrap_fence(module, monkeypatch, ["recover"])
    with pytest.raises(module.XinaoError) as failure:
        module.inspect_capability()
    assert failure.value.reason_code == "RECOVERY_REQUIRED"


@pytest.mark.parametrize("command", (["inspect"], ["research", "--question", "q"]))
def test_thin_bootstrap_blocks_pending_inspect_and_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    _terminal_pointer(runtime, manifest, manifest_path, state="POINTER_SWITCHED")
    bootstrap = _bootstrap_module()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._runtime_entry_locked(command, tmp_path / "state")
    assert failure.value.reason_code == "RECOVERY_REQUIRED"


def test_thin_bootstrap_requires_verified_txn_and_pointer_hash_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    _pointer, journal, journal_path = _terminal_pointer(runtime, manifest, manifest_path)
    bootstrap = _bootstrap_module()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    expected_runtime, expected_payload, fence = bootstrap._runtime_entry_locked(
        ["inspect"], tmp_path / "state"
    )
    assert expected_runtime == Path(manifest["skill_bundle_path"]) / "scripts" / "xinao_runtime.py"
    assert expected_payload == expected_runtime.read_bytes()
    assert fence["selected_runtime_sha256"] == runtime._sha256_bytes(expected_payload)
    assert set(fence) == runtime.BOOTSTRAP_FENCE_KEYS

    journal["terminal_pointer_sha256"] = "0" * 64
    runtime._write_json_atomic(journal_path, journal)
    with pytest.raises(bootstrap.BootstrapError) as hash_failure:
        bootstrap._runtime_entry_locked(["inspect"], tmp_path / "state")
    assert hash_failure.value.reason_code == "ACTIVATION_POINTER_BINDING_MISMATCH"

    journal["terminal_pointer_sha256"] = runtime._sha256(runtime._state_paths()["pointer"])
    journal["txn_id"] = "xra_20260730T120000_" + "f" * 16
    runtime._write_json_atomic(journal_path, journal)
    with pytest.raises(bootstrap.BootstrapError) as txn_failure:
        bootstrap._runtime_entry_locked(["inspect"], tmp_path / "state")
    assert txn_failure.value.reason_code == "ACTIVATION_TRANSACTION_BINDING_MISMATCH"


def test_thin_bootstrap_loads_runtime_only_from_exact_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    _terminal_pointer(runtime, manifest, manifest_path)
    bootstrap = _bootstrap_module()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    runtime_path, runtime_payload, fence = bootstrap._runtime_entry_locked(
        ["inspect"], tmp_path / "state"
    )
    bundle_manifest = json.loads(
        Path(manifest["skill_bundle_manifest_path"]).read_text(encoding="utf-8")
    )
    row = next(
        item
        for item in bundle_manifest["files"]
        if item["relative_path"] == "scripts/xinao_runtime.py"
    )
    assert runtime_path == Path(manifest["skill_bundle_path"]) / row["relative_path"]
    assert runtime._sha256(runtime_path) == row["sha256"]
    assert runtime._sha256_bytes(runtime_payload) == row["sha256"]
    assert fence["selected_runtime_sha256"] == row["sha256"]


def test_runtime_consumes_exact_bootstrap_fence_under_activation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    with module._activation_lock():
        observed = module._validate_bootstrap_fence_locked("inspect")
    assert observed == fence
    assert module.BOOTSTRAP_FENCE_ENVIRONMENT not in os.environ
    observed["pointer_sha256"] = "0" * 64
    with module._activation_lock():
        reread = module._validate_bootstrap_fence_locked("inspect", expected=fence)
    assert reread == fence
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(fence, sort_keys=True, separators=(",", ":")),
    )
    with module._activation_lock():
        with pytest.raises(module.XinaoError) as pollution:
            module._validate_bootstrap_fence_locked("inspect", expected=fence)
    assert pollution.value.reason_code == "BOOTSTRAP_FENCE_ENVIRONMENT_REAPPEARED"
    assert module.BOOTSTRAP_FENCE_ENVIRONMENT not in os.environ


@pytest.mark.parametrize("mutation", ("missing_key", "extra_key"))
def test_bootstrap_fence_rejects_missing_or_extra_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    candidate = dict(fence)
    if mutation == "missing_key":
        candidate.pop("selected_runtime_sha256")
    else:
        candidate["unexpected"] = True
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(candidate, sort_keys=True, separators=(",", ":")),
    )
    with pytest.raises(module.XinaoError) as failure:
        module._load_bootstrap_fence()
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_INVALID"


def test_bootstrap_fence_rejects_pointer_drift_under_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    pointer_path = module._state_paths()["pointer"]
    pointer = module._load_json(pointer_path)
    pointer["switched_at"] = "2026-07-30T12:00:02Z"
    module._write_json_atomic(pointer_path, pointer)
    with module._activation_lock():
        with pytest.raises(module.XinaoError) as failure:
            module._validate_bootstrap_fence_locked("inspect", expected=fence)
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_bootstrap_fence_rejects_pending_transaction_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    second, second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"pending-drift"
    )
    with module._activation_lock():
        current = module._load_current_context()
        module._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
        with pytest.raises(module.XinaoError) as failure:
            module._validate_bootstrap_fence_locked("recover", expected=fence)
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_bootstrap_fence_rejects_executed_runtime_digest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    drifted_runtime = tmp_path / "drifted-runtime.py"
    drifted_runtime.write_text("raise RuntimeError('drift')\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(drifted_runtime))
    with module._activation_lock():
        with pytest.raises(module.XinaoError) as failure:
            module._validate_bootstrap_fence_locked("inspect", expected=fence)
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_RUNTIME_DRIFT"


def test_inspect_revalidates_fence_before_reporting_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    monkeypatch.setattr(module, "_validate_release_image_identity", lambda _release: "docker")

    def drift_pointer(_release):
        pointer_path = module._state_paths()["pointer"]
        pointer = module._load_json(pointer_path)
        pointer["switched_at"] = "2026-07-30T12:00:03Z"
        module._write_json_atomic(pointer_path, pointer)
        return "docker", module._validate_charter()

    monkeypatch.setattr(module, "_validate_release_for_invoke", drift_pointer)
    with pytest.raises(module.XinaoError) as failure:
        module.inspect_capability()
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_inspect_revalidates_fence_before_returning_error_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    monkeypatch.setattr(module, "_validate_release_image_identity", lambda _release: "docker")

    def drift_then_fail(_release):
        pointer_path = module._state_paths()["pointer"]
        pointer = module._load_json(pointer_path)
        pointer["switched_at"] = "2026-07-30T12:00:05Z"
        module._write_json_atomic(pointer_path, pointer)
        raise module.XinaoError("ENGINE_UNAVAILABLE", "injected")

    monkeypatch.setattr(module, "_validate_release_for_invoke", drift_then_fail)
    with pytest.raises(module.XinaoError) as failure:
        module.inspect_capability()
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_research_revalidates_fence_before_container_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _install_bootstrap_fence(module, monkeypatch, ["research", "--question", "q"])
    _auth(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "_validate_release_source_identity",
        lambda _release: (
            module._validate_charter(),
            {
                "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
                "provider_egress_runtime_verified": False,
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "_require_host_egress_boundary",
        lambda _lock=None: {
            "internal_network_name": "xinao_researcher_internal",
            "internal_network_id": "netid",
            "proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
            "proxy_container_id": "cid",
            "proxy_image_id": "sha256:" + "d" * 64,
            "allowlist_sha256": "a" * 64,
            "proxy_config_sha256": "b" * 64,
            "live_proxy_config_sha256": "b" * 64,
            "posture_sha256": "c" * 64,
            "live_seal_sha256": "e" * 64,
            "live_seal": {"expires_at": "2099-01-01T00:00:00Z"},
            "docker_engine_observational_id": "engine|desktop",
            "provider_egress_runtime_verified": True,
            "completion_claim_allowed": False,
            "posture": {},
            "observed": {},
        },
    )

    def drift_pointer(_release):
        pointer_path = module._state_paths()["pointer"]
        pointer = module._load_json(pointer_path)
        pointer["switched_at"] = "2026-07-30T12:00:04Z"
        module._write_json_atomic(pointer_path, pointer)
        return "docker", module._validate_charter()

    monkeypatch.setattr(module, "_validate_release_for_invoke", drift_pointer)
    monkeypatch.setattr(
        module, "_run", lambda *_args, **_kwargs: pytest.fail("Docker must not run")
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research("q", None, [])
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_egress_boundary_fails_before_docker_or_auth_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, _manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    runtime_lock = module._load_json(module.RUNTIME_LOCK_PATH)
    runtime_lock["provider_egress_runtime_verified"] = False
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(
        module,
        "_validate_release_source_identity",
        lambda _release: (module._validate_charter(), runtime_lock),
    )
    # Missing live seal must fail before docker/auth.
    monkeypatch.setattr(module, "_docker", lambda: pytest.fail("Docker must not be touched"))
    monkeypatch.setattr(module, "DEFAULT_AUTH_PATH", tmp_path / "missing-auth.json")
    with pytest.raises(module.XinaoError) as failure:
        module._validate_release_for_invoke(manifest)
    assert failure.value.reason_code in {
        "EGRESS_BOUNDARY_UNAVAILABLE",
        "EGRESS_POSTURE_MISSING",
        "EGRESS_LIVE_SEAL_MISSING",
    }


def test_research_egress_failure_precedes_auth_snapshot_and_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _install_bootstrap_fence(module, monkeypatch, ["research", "--question", "q"])
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(
        module,
        "_validate_release_source_identity",
        lambda _release: (
            module._validate_charter(),
            {
                "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
                "provider_egress_runtime_verified": False,
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "_snapshot_material_sources",
        lambda _paths: pytest.fail("auth/material snapshot must not run"),
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research("q", None, [])
    assert failure.value.reason_code in {
        "EGRESS_BOUNDARY_UNAVAILABLE",
        "EGRESS_POSTURE_MISSING",
        "EGRESS_LIVE_SEAL_MISSING",
    }
    assert not (tmp_path / "runs").exists()


def test_material_snapshot_holds_one_auth_identity_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    auth = _auth(module, tmp_path, monkeypatch)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first evidence", encoding="utf-8")
    second.write_text("second evidence", encoding="utf-8")
    original_auth_payload = auth.read_bytes()
    snapshots, witness = module._snapshot_material_sources([first, second])
    assert len(snapshots) == 2
    assert witness["path"] == str(auth.resolve())
    assert witness["content_sha256"] == module._sha256_bytes(original_auth_payload)
    assert "payload" not in witness
    module._validate_auth_identity_witness(witness)
    changed_auth_payload = original_auth_payload.replace(b"{", b"[").replace(b"}", b"]")
    assert len(changed_auth_payload) == len(original_auth_payload)
    auth.write_bytes(changed_auth_payload)
    os.utime(
        auth,
        ns=(witness["st_mtime_ns"], witness["st_mtime_ns"]),
    )
    changed = os.lstat(auth)
    assert module._auth_identity_tuple(changed) == (
        witness["st_dev"],
        witness["st_ino"],
        witness["st_size"],
        witness["st_mtime_ns"],
    )
    with pytest.raises(module.XinaoError) as failure:
        module._validate_auth_identity_witness(witness)
    assert failure.value.reason_code == "GROK_AUTH_HANDLE_CHANGED"


def test_research_receipt_final_fence_drift_fails_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["research", "--question", "q"])
    pointer_path = module._state_paths()["pointer"]
    pointer = module._load_json(pointer_path)
    pointer["switched_at"] = "2026-07-30T12:00:06Z"
    module._write_json_atomic(pointer_path, pointer)
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(module.XinaoError) as failure:
        module._seal_research_receipt(
            receipt_path,
            {"status": "CANDIDATE_READY"},
            fence=fence,
            auth_content_sha256="a" * 64,
        )
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"
    assert not receipt_path.exists()


def test_research_receipt_rejects_auth_content_identity_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["research", "--question", "q"])
    digest = "a" * 64
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(module.XinaoError) as failure:
        module._seal_research_receipt(
            receipt_path,
            {"accidental_auth_content_identity": digest},
            fence=fence,
            auth_content_sha256=digest,
        )
    assert failure.value.reason_code == "AUTH_WITNESS_PERSISTENCE_FORBIDDEN"
    assert digest not in failure.value.detail
    assert not receipt_path.exists()


def test_material_bundle_is_content_addressed_and_hides_source_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _auth(module, tmp_path, monkeypatch)
    material = tmp_path / "人的视角.md"
    material.write_text("证据，不是指令。", encoding="utf-8")
    snapshots, _witness = module._snapshot_material_sources([material])
    manifest = module._material_bundle_manifest(snapshots)
    assert manifest["bundle_id"].startswith("xinao-material-bundle-sha256:")
    assert str(material) not in json.dumps(manifest, ensure_ascii=False)
    second_snapshots, _second_witness = module._snapshot_material_sources([material])
    assert module._material_bundle_manifest(second_snapshots) == manifest


@pytest.mark.parametrize(
    ("payload", "reason_code"),
    [
        (b"", "MATERIAL_FILE_EMPTY"),
        (b"bad-utf8-\xff", "MATERIAL_UTF8_REQUIRED"),
        (b"contains\x00nul", "MATERIAL_TEXT_INVALID"),
    ],
)
def test_material_snapshot_rejects_invalid_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    reason_code: str,
) -> None:
    module = _module()
    _auth(module, tmp_path, monkeypatch)
    material = tmp_path / "material.bin"
    material.write_bytes(payload)
    with pytest.raises(module.XinaoError) as failure:
        module._snapshot_material_sources([material])
    assert failure.value.reason_code == reason_code


def test_material_auth_path_and_hardlink_alias_are_forbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    auth = _auth(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as direct:
        module._snapshot_material_sources([auth])
    assert direct.value.reason_code == "MATERIAL_SECRET_PATH_FORBIDDEN"
    alias = tmp_path / "auth-alias.json"
    try:
        os.link(auth, alias)
    except OSError:
        pytest.skip("hardlinks unavailable")
    with pytest.raises(module.XinaoError) as linked:
        module._snapshot_material_sources([alias])
    assert linked.value.reason_code in {
        "MATERIAL_SECRET_PATH_FORBIDDEN",
        "MATERIAL_HARDLINK_FORBIDDEN",
    }


def _valid_provider_result() -> dict[str, object]:
    return {
        "provider_stop_reason": "EndTurn",
        "provider_num_turns": 1,
        "provider_session_id_present": True,
        "provider_request_id_present": True,
        # Producer formal result.json keys (entrypoint #159 raw ids).
        "provider_session_id": "session-prod-001",
        "provider_request_id": "request-prod-001",
        "provider_model_usage": {"grok-4.5-build": {"inputTokens": 10, "modelCalls": 1}},
        "usage": {"total_tokens": 12},
    }


def test_provider_effect_requires_exact_observed_model_and_integer_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    runtime_lock = module._load_json(module.RUNTIME_LOCK_PATH)
    assert module._validate_provider_effect(_valid_provider_result(), runtime_lock) == (
        "grok-4.5-build",
        1,
    )
    invalid_values = (
        {"grok-4.5": {"modelCalls": 1}},
        {
            "grok-4.5-build": {"modelCalls": 1},
            "fake": {"modelCalls": 1},
        },
        {"grok-4.5-build": {"modelCalls": True}},
        {"grok-4.5-build": {"modelCalls": 0}},
    )
    for model_usage in invalid_values:
        result = _valid_provider_result()
        result["provider_model_usage"] = model_usage
        with pytest.raises(module.XinaoError) as failure:
            module._validate_provider_effect(result, runtime_lock)
        assert failure.value.reason_code == "PROVIDER_EFFECT_EVIDENCE_INVALID"


def _valid_container_inspect(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    input_root = tmp_path / "input"
    materials_root = tmp_path / "materials"
    output_root = tmp_path / "output"
    auth_path = tmp_path / "auth.json"
    image_id = "sha256:" + "a" * 64
    endpoint = "http://xinao-researcher-egress-proxy:3128"
    network_name = "xinao_researcher_internal"
    network_id = "net_" + "c" * 12
    inspect: dict[str, object] = {
        "Image": image_id,
        "HostConfig": {
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": network_name,
            "PidsLimit": 128,
            "Memory": 2147483648,
            "NanoCpus": 2000000000,
            "Privileged": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "Tmpfs": {
                "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
                "/grok-home": "rw,nosuid,nodev,size=256m,mode=0700",
            },
        },
        "Config": {
            "Env": [
                "XINAO_CHAIN_CLASS=scientific_researcher",
                f"HTTP_PROXY={endpoint}",
                f"HTTPS_PROXY={endpoint}",
                f"http_proxy={endpoint}",
                f"https_proxy={endpoint}",
            ]
        },
        "NetworkSettings": {"Networks": {network_name: {"NetworkID": network_id}}},
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(input_root),
                "Destination": "/input",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(materials_root),
                "Destination": "/materials",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(output_root),
                "Destination": "/output",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": str(auth_path),
                "Destination": "/grok-home/auth.json",
                "RW": False,
            },
        ],
    }
    arguments: dict[str, object] = {
        "image_id": image_id,
        "input_root": input_root,
        "materials_root": materials_root,
        "output_root": output_root,
        "auth_path": auth_path,
        "internal_network_name": network_name,
        "internal_network_id": network_id,
        "proxy_endpoint": endpoint,
    }
    return inspect, arguments


@pytest.mark.parametrize(
    ("field", "invalid_value", "reason_code"),
    (
        ("PidsLimit", 129, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("PidsLimit", True, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("CapDrop", ["ALL", "SYS_ADMIN"], "CONTAINER_CAP_DROP_INVALID"),
        ("CapAdd", ["SYS_ADMIN"], "CONTAINER_CAP_ADD_INVALID"),
        (
            "SecurityOpt",
            ["no-new-privileges:true", "seccomp=unconfined"],
            "CONTAINER_NO_NEW_PRIVILEGES_MISSING",
        ),
        ("Memory", 2147483647, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("Memory", 2147483648.0, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("NanoCpus", 1999999999, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("NanoCpus", 2000000000.0, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("Privileged", True, "CONTAINER_PRIVILEGE_BOUNDARY_INVALID"),
        (
            "RestartPolicy",
            {"Name": "no", "MaximumRetryCount": False},
            "CONTAINER_RESTART_POLICY_INVALID",
        ),
        (
            "RestartPolicy",
            {"Name": "always", "MaximumRetryCount": 0},
            "CONTAINER_RESTART_POLICY_INVALID",
        ),
        (
            "Tmpfs",
            {"/tmp": "rw,nosuid,nodev,size=256m,mode=1777"},
            "CONTAINER_TMPFS_INVALID",
        ),
        (
            "Tmpfs",
            {
                "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
                "/grok-home": "rw,nosuid,nodev,size=256m,mode=0700",
                "/extra": "rw",
            },
            "CONTAINER_TMPFS_INVALID",
        ),
    ),
)
def test_container_inspect_requires_exact_runtime_security_values(
    tmp_path: Path,
    field: str,
    invalid_value: object,
    reason_code: str,
) -> None:
    module = _module()
    inspect, arguments = _valid_container_inspect(tmp_path)
    module._validate_container_inspect(inspect, **arguments)
    host = inspect["HostConfig"]
    assert isinstance(host, dict)
    host["CapAdd"] = []
    module._validate_container_inspect(inspect, **arguments)
    host[field] = invalid_value
    with pytest.raises(module.XinaoError) as failure:
        module._validate_container_inspect(inspect, **arguments)
    assert failure.value.reason_code == reason_code


@pytest.mark.parametrize(
    "delta",
    (
        {"Status": "running"},
        {"Running": True},
        {"ExitCode": True},
        {"ExitCode": 1},
        {"OOMKilled": True},
        {"Error": "boom"},
    ),
)
def test_container_terminal_state_is_strict(delta: dict[str, object]) -> None:
    module = _module()
    terminal = {
        "Status": "exited",
        "Running": False,
        "ExitCode": 0,
        "OOMKilled": False,
        "Error": "",
        "Paused": False,
        "Restarting": False,
        "Dead": False,
    }
    assert module._validate_container_terminal_state(terminal) == terminal
    terminal.update(delta)
    with pytest.raises(module.XinaoError) as failure:
        module._validate_container_terminal_state(terminal)
    assert failure.value.reason_code == "CONTAINER_TERMINAL_STATE_INVALID"


def test_terminal_attestation_is_bounded_canonical_and_hash_bound() -> None:
    module = _module()
    value = {
        "schema_version": "xinao.researcher_terminal_attestation.v1",
        "status": "CANDIDATE_READY",
        "result_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "observed_model_id": "grok-4.5-build",
        "observed_model_calls": 1,
    }
    payload = module._canonical_bytes(value)
    assert (
        module._validate_terminal_attestation(
            payload,
            request_sha256="b" * 64,
            result_sha256="a" * 64,
            result_status="CANDIDATE_READY",
            observed_model_id="grok-4.5-build",
            observed_model_calls=1,
        )
        == value
    )
    with pytest.raises(module.XinaoError) as tampered:
        module._validate_terminal_attestation(
            payload,
            request_sha256="0" * 64,
            result_sha256="a" * 64,
            result_status="CANDIDATE_READY",
            observed_model_id="grok-4.5-build",
            observed_model_calls=1,
        )
    assert tampered.value.reason_code == "CONTAINER_TERMINAL_ATTESTATION_BINDING_INVALID"
    with pytest.raises(module.XinaoError) as oversized:
        module._validate_terminal_attestation(
            b"x" * (module.MAX_TERMINAL_ATTESTATION_BYTES + 1),
            request_sha256="b" * 64,
            result_sha256="a" * 64,
            result_status="CANDIDATE_READY",
            observed_model_id="grok-4.5-build",
            observed_model_calls=1,
        )
    assert oversized.value.reason_code == "CONTAINER_TERMINAL_ATTESTATION_INVALID"


def _production_shaped_material_result_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, dict[str, object], dict[str, object], dict[str, str]]:
    """Build a production-shaped container result accepted by host material binding."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    module = _module()
    _auth(module, tmp_path, monkeypatch)
    source = tmp_path / "material.txt"
    source.write_text("evidence", encoding="utf-8")
    snapshots, _witness = module._snapshot_material_sources([source])
    manifest = module._material_bundle_manifest(snapshots)
    manifest_sha = module._sha256_bytes(module._canonical_bytes(manifest))
    packet = module._material_packet_bytes(manifest, snapshots)
    packet_sha = module._sha256_bytes(packet)
    effective_sha = module._sha256_bytes(module._effective_prompt_bytes("base", packet))
    entry = manifest["materials"][0]
    candidate = {
        "schema_version": "xinao.research_candidate.v2",
        "status": "CANDIDATE_READY",
        "research_question": "q",
        "as_of": "2026-07-30T00:00:00Z",
        "material_bundle_id": manifest["bundle_id"],
        "material_refs_used": [{"material_id": entry["material_id"], "sha256": entry["sha256"]}],
        "summary": "candidate only",
        "hypotheses": ["one hypothesis"],
        "competing_explanations": ["one competing explanation"],
        "methods": ["bounded material analysis"],
        "evidence_used": [
            {
                "material_id": entry["material_id"],
                "finding": "bounded finding",
                "locator": "whole file",
            }
        ],
        "counterevidence": [],
        "limitations": ["candidate evidence only"],
        "next_evidence": ["independent observation"],
        "no_action_intent": {
            "target_ref": "draw.20260730-001",
            "target_open_time": "2026-07-30T01:00:00Z",
            "freeze_deadline": "2026-07-30T00:59:00Z",
            "knowledge_cutoff": "2026-07-30T00:00:00Z",
            "odds_version_ref": "odds.special-number.test.v1",
            "rule_ref": "special-number-rule.v1",
        },
        "account_identity": "RESEARCHER_ACCOUNT_NO_ACTION",
    }
    request_sha = "1" * 64
    prompt_sha = "2" * 64
    output_schema_sha = module._sha256(module.OUTPUT_SCHEMA_PATH)
    result: dict[str, object] = {
        "schema_version": "xinao.researcher_container_result.v2",
        "status": "CANDIDATE_READY",
        "reason_codes": [],
        "candidate": candidate,
        "request_sha256": request_sha,
        "prompt_sha256": prompt_sha,
        "output_schema_sha256": output_schema_sha,
        "material_bundle_id": manifest["bundle_id"],
        "material_manifest_sha256": manifest_sha,
        "material_packet_sha256": packet_sha,
        "effective_prompt_sha256": effective_sha,
        "material_refs_available": [entry["material_id"]],
        "provider": "grok",
        "requested_model": "grok-4.5",
        **_valid_provider_result(),
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
    }
    binding = {
        "request_sha256": request_sha,
        "prompt_sha256": prompt_sha,
        "output_schema_sha256": output_schema_sha,
        "manifest_sha256": manifest_sha,
        "material_packet_sha256": packet_sha,
        "effective_prompt_sha256": effective_sha,
        "question": "q",
        "as_of": "2026-07-30T00:00:00Z",
    }
    return module, result, manifest, binding


def test_material_result_binding_requires_real_supplied_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, result, manifest, binding = _production_shaped_material_result_binding(
        tmp_path, monkeypatch
    )
    module._validate_material_result_binding(result, manifest=manifest, **binding)
    candidate = result["candidate"]
    assert isinstance(candidate, dict)
    candidate["material_refs_used"] = []
    candidate["evidence_used"] = []
    with pytest.raises(module.XinaoError) as unbound:
        module._validate_material_result_binding(result, manifest=manifest, **binding)
    assert unbound.value.reason_code == "RESEARCH_CANDIDATE_MATERIAL_USE_UNBOUND"


def _researcher_action_core() -> dict[str, object]:
    return {
        "panel": "A",
        "selected_number": 7,
        "stake": "1.0000",
        "target_ref": "draw.20260730-001",
        "target_open_time": "2026-07-30T01:00:00Z",
        "freeze_deadline": "2026-07-30T00:59:00Z",
        "knowledge_cutoff": "2026-07-30T00:00:00Z",
        "odds_version_ref": "odds.special-number.test.v1",
        "baseline_ref": "BO0001",
        "risk_policy_ref": "risk.test.v1",
        "rule_ref": "special-number-rule.v1",
    }


def test_material_result_binding_accepts_exact_action_or_no_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, result, manifest, binding = _production_shaped_material_result_binding(
        tmp_path, monkeypatch
    )
    module._validate_material_result_binding(result, manifest=manifest, **binding)

    candidate = result["candidate"]
    assert isinstance(candidate, dict)
    candidate.pop("no_action_intent")
    candidate.pop("account_identity")
    # A generic research signal does not become account behavior merely because
    # its evidence is ready for Owner review.
    module._validate_material_result_binding(result, manifest=manifest, **binding)

    candidate["no_action_intent"] = {
        "target_ref": "draw.20260730-001",
        "target_open_time": "2026-07-30T01:00:00Z",
        "freeze_deadline": "2026-07-30T00:59:00Z",
        "knowledge_cutoff": "2026-07-30T00:00:00Z",
        "odds_version_ref": "odds.special-number.test.v1",
        "rule_ref": "special-number-rule.v1",
    }
    candidate["account_identity"] = "RESEARCHER_ACCOUNT_NO_ACTION"
    module._validate_material_result_binding(result, manifest=manifest, **binding)

    candidate.pop("no_action_intent")
    candidate["executable_account_decision"] = _researcher_action_core()
    candidate["account_identity"] = "ACTION"
    module._validate_material_result_binding(result, manifest=manifest, **binding)

    # account_identity is an optional redundant readback, never a branch selector.
    candidate.pop("account_identity")
    module._validate_material_result_binding(result, manifest=manifest, **binding)

    insufficient_module, insufficient, insufficient_manifest, insufficient_binding = (
        _production_shaped_material_result_binding(tmp_path / "insufficient", monkeypatch)
    )
    insufficient_candidate = insufficient["candidate"]
    assert isinstance(insufficient_candidate, dict)
    insufficient["status"] = "INSUFFICIENT_EVIDENCE"
    insufficient_candidate["status"] = "INSUFFICIENT_EVIDENCE"
    insufficient_candidate.pop("no_action_intent")
    insufficient_candidate.pop("account_identity")
    insufficient_module._validate_material_result_binding(
        insufficient,
        manifest=insufficient_manifest,
        **insufficient_binding,
    )


def test_material_result_binding_accepts_actor_only_intent_and_normalized_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, result, manifest, binding = _production_shaped_material_result_binding(
        tmp_path, monkeypatch
    )
    candidate = result["candidate"]
    assert isinstance(candidate, dict)
    candidate.pop("no_action_intent")
    candidate.pop("account_identity")
    intent = {
        "schema_version": "xinao.actor_authored_behavior_intent.v1",
        "authored_at": "2026-07-30T00:30:00+00:00",
        "decision_kind": "ACTION",
        "panel": "B",
        "selected_number": 49,
        "stake": "3.2500",
        "research_rationale": "The live evidence supports this exposure.",
    }
    candidate["complete_actor_behavior_intent"] = intent
    module._validate_material_result_binding(result, manifest=manifest, **binding)

    normalized = {
        **intent,
        "authored_at": "2026-07-30T00:30:00Z",
        "after_hit_response": None,
        "after_miss_response": None,
        "next_round_or_stop_response": None,
    }
    intent["content_hash"] = module._sha256_bytes(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    module._validate_material_result_binding(result, manifest=manifest, **binding)

    intent["content_hash"] = "0" * 64
    with pytest.raises(module.XinaoError) as forged:
        module._validate_material_result_binding(result, manifest=manifest, **binding)
    assert forged.value.reason_code == "RESEARCH_CANDIDATE_ACTOR_INTENT_INVALID"


def test_material_result_binding_rejects_actor_intent_status_or_legacy_choice_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, result, manifest, binding = _production_shaped_material_result_binding(
        tmp_path, monkeypatch
    )
    candidate = result["candidate"]
    assert isinstance(candidate, dict)
    candidate["complete_actor_behavior_intent"] = {
        "schema_version": "xinao.actor_authored_behavior_intent.v1",
        "authored_at": "2026-07-30T00:30:00Z",
        "decision_kind": "ACTION",
        "panel": "A",
        "selected_number": 7,
        "stake": "2.0000",
        "research_rationale": "actor-authored choice",
    }
    with pytest.raises(module.XinaoError) as mismatch:
        module._validate_material_result_binding(result, manifest=manifest, **binding)
    assert mismatch.value.reason_code == (
        "RESEARCH_CANDIDATE_ACTOR_INTENT_BRANCH_MISMATCH"
    )

    candidate.pop("no_action_intent")
    candidate.pop("account_identity")
    result["status"] = "INSUFFICIENT_EVIDENCE"
    candidate["status"] = "INSUFFICIENT_EVIDENCE"
    with pytest.raises(module.XinaoError) as insufficient:
        module._validate_material_result_binding(result, manifest=manifest, **binding)
    assert insufficient.value.reason_code == (
        "RESEARCH_CANDIDATE_ACTOR_INTENT_STATUS_INVALID"
    )


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("identity_without_branch", "RESEARCH_CANDIDATE_DECISION_BRANCH_REQUIRED"),
        (
            "both_branches",
            "RESEARCH_CANDIDATE_DECISION_BRANCH_CONFLICT",
        ),
        (
            "identity_mismatch",
            "RESEARCH_CANDIDATE_ACCOUNT_IDENTITY_INVALID",
        ),
        (
            "no_action_shape",
            "RESEARCH_CANDIDATE_NO_ACTION_INVALID",
        ),
        (
            "insufficient_with_branch",
            "RESEARCH_CANDIDATE_DECISION_BRANCH_STATUS_INVALID",
        ),
    ],
)
def test_material_result_binding_rejects_decision_branch_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    reason_code: str,
) -> None:
    module, result, manifest, binding = _production_shaped_material_result_binding(
        tmp_path, monkeypatch
    )
    candidate = result["candidate"]
    assert isinstance(candidate, dict)
    if mutation == "identity_without_branch":
        candidate.pop("no_action_intent")
    elif mutation == "both_branches":
        candidate["executable_account_decision"] = _researcher_action_core()
    elif mutation == "identity_mismatch":
        candidate["account_identity"] = "ACTION"
    elif mutation == "no_action_shape":
        no_action = candidate["no_action_intent"]
        assert isinstance(no_action, dict)
        no_action.pop("knowledge_cutoff")
    elif mutation == "insufficient_with_branch":
        result["status"] = "INSUFFICIENT_EVIDENCE"
        candidate["status"] = "INSUFFICIENT_EVIDENCE"
    else:  # pragma: no cover - exhaustive parametrization guard
        raise AssertionError(mutation)
    with pytest.raises(module.XinaoError) as failure:
        module._validate_material_result_binding(result, manifest=manifest, **binding)
    assert failure.value.reason_code == reason_code


def test_material_result_binding_admits_producer_raw_provider_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host exact-key allowlist must accept production result.json with raw provider ids."""

    module, result, manifest, binding = _production_shaped_material_result_binding(
        tmp_path, monkeypatch
    )
    assert "provider_session_id" in result
    assert "provider_request_id" in result
    assert result["provider_session_id_present"] is True
    assert result["provider_request_id_present"] is True
    module._validate_material_result_binding(result, manifest=manifest, **binding)


@pytest.mark.parametrize(
    ("mutate", "reason_code"),
    [
        (
            lambda r: r.pop("provider_session_id"),
            "RESEARCH_RESULT_FIELDS_INVALID",
        ),
        (
            lambda r: r.pop("provider_request_id"),
            "RESEARCH_RESULT_FIELDS_INVALID",
        ),
        (
            lambda r: r.__setitem__("extra_provider_field", "nope"),
            "RESEARCH_RESULT_FIELDS_INVALID",
        ),
        (
            lambda r: r.__setitem__("provider_session_id", ""),
            "RESEARCH_RESULT_PROVIDER_ID_INVALID",
        ),
        (
            lambda r: r.__setitem__("provider_request_id", ""),
            "RESEARCH_RESULT_PROVIDER_ID_INVALID",
        ),
        (
            lambda r: r.__setitem__("provider_session_id", " \t\r\n"),
            "RESEARCH_RESULT_PROVIDER_ID_INVALID",
        ),
        (
            lambda r: r.__setitem__("provider_request_id", "request\x00hidden"),
            "RESEARCH_RESULT_PROVIDER_ID_INVALID",
        ),
        (
            lambda r: r.__setitem__("provider_session_id", "s" * 4097),
            "RESEARCH_RESULT_PROVIDER_ID_INVALID",
        ),
        (
            lambda r: r.__setitem__("provider_session_id", 12345),
            "RESEARCH_RESULT_PROVIDER_ID_INVALID",
        ),
        (
            lambda r: r.__setitem__("provider_request_id", None),
            "RESEARCH_RESULT_PROVIDER_ID_INVALID",
        ),
        (
            lambda r: (
                r.__setitem__("provider_session_id_present", False),
                r.__setitem__("provider_session_id", "still-present"),
            ),
            "RESEARCH_RESULT_PROVIDER_ID_INCONSISTENT",
        ),
        (
            lambda r: (
                r.__setitem__("provider_request_id_present", False),
                r.__setitem__("provider_request_id", "still-present"),
            ),
            "RESEARCH_RESULT_PROVIDER_ID_INCONSISTENT",
        ),
        (
            lambda r: r.__setitem__("provider_session_id_present", "yes"),
            "RESEARCH_RESULT_FIELDS_INVALID",
        ),
    ],
)
def test_material_result_binding_rejects_invalid_raw_provider_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: object,
    reason_code: str,
) -> None:
    module, result, manifest, binding = _production_shaped_material_result_binding(
        tmp_path, monkeypatch
    )
    mutate(result)
    with pytest.raises(module.XinaoError) as failure:
        module._validate_material_result_binding(result, manifest=manifest, **binding)
    assert failure.value.reason_code == reason_code


def test_bounded_result_reader_rejects_oversized_json(
    tmp_path: Path,
) -> None:
    module = _module()
    result = tmp_path / "result.json"
    result.write_bytes(b'{"x":"' + b"a" * 128 + b'"}\n')
    with pytest.raises(module.XinaoError) as failure:
        module._load_json(result, maximum_bytes=32)
    assert failure.value.reason_code == "JSON_READ_FAILED"


def _copy_skill_tree(source: Path, destination: Path, *, newline: bytes | None = None) -> None:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = path.read_bytes()
        if newline is not None and path.suffix.lower() in {
            ".md",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".txt",
        }:
            text = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            if newline == b"\r\n":
                payload = text.replace(b"\n", b"\r\n")
            else:
                payload = text
        target.write_bytes(payload)


def _materialize_real_legacy_skill_tree(destination: Path, *, newline: bytes) -> None:
    """Materialize the true b916 v1 Skill bytes, not a projection of current source."""

    encoded = zlib.decompress(base64.b85decode(LEGACY_XINAO_FIXTURE_B85)).decode("utf-8")
    files = json.loads(encoded)
    assert isinstance(files, dict)
    assert sorted(files) == [
        "SKILL.md",
        "agents/openai.yaml",
        "references/capabilities.v1.json",
        "references/meta.md",
        "references/researcher-charter.v1.json",
        "references/researcher-output.v1.schema.json",
        "references/researcher-runtime-lock.v1.json",
        "scripts/xinao.py",
    ]
    for relative, encoded_payload in files.items():
        payload = base64.b64decode(encoded_payload, validate=True)
        assert (
            hashlib.sha256(payload).hexdigest()
            == (LEGACY_XINAO_FIXTURE_MANIFEST["files"][relative])
        )
        if Path(relative).suffix.lower() in {
            ".md",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".txt",
        }:
            payload = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            if newline == b"\r\n":
                payload = payload.replace(b"\n", b"\r\n")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    launcher = destination / "scripts" / "xinao.py"
    assert not (destination / "scripts" / "xinao_runtime.py").exists()
    assert b"bootstrap-migrate" not in launcher.read_bytes()
    assert b"recover" not in launcher.read_bytes()
    if newline == b"\r\n":
        assert hashlib.sha256(launcher.read_bytes()).hexdigest() == (
            LEGACY_INSTALLED_LAUNCHER_SHA256
        )


def _stage_source_rendering(
    module,
    release_id: str,
    *,
    newline: bytes,
    marker: bytes | None = None,
) -> Path:
    root = module._state_paths()["migration_root"] / "test-only-legacy-fixture" / release_id
    if root.exists():
        import shutil

        shutil.rmtree(root)
    _materialize_real_legacy_skill_tree(root, newline=newline)
    # Keep the parameter for older call sites, but never fabricate non-legacy bytes.
    del marker
    return root


def _legacy_skill_hashes_for_tree(module, root: Path) -> dict[str, str]:
    skill_side = {
        "skill_md_sha256": module._sha256(root / "SKILL.md"),
        "skill_invoker_sha256": module._sha256(root / "scripts" / "xinao.py"),
        "capability_registry_sha256": module._sha256(root / "references" / "capabilities.v1.json"),
        "charter_sha256": module._sha256(root / "references" / "researcher-charter.v1.json"),
        "runtime_lock_sha256": module._sha256(
            root / "references" / "researcher-runtime-lock.v1.json"
        ),
        "meta_sha256": module._sha256(root / "references" / "meta.md"),
        "output_schema_sha256": module._sha256(
            root / "references" / "researcher-output.v1.schema.json"
        ),
    }
    skill_side["dockerfile_sha256"] = "1" * 64
    skill_side["entrypoint_sha256"] = "2" * 64
    return skill_side


def _write_pure_v1_release(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_character: str,
    newline: bytes,
    marker: bytes,
    release_suffix: str,
) -> tuple[dict[str, object], Path, Path]:
    state = _state(module, tmp_path, monkeypatch)
    release_id = f"researcher-1.0.0-{release_suffix}"
    rendering = _stage_source_rendering(module, release_id, newline=newline, marker=marker)
    skill_hashes = _legacy_skill_hashes_for_tree(module, rendering)
    source_identity = {
        "source_commit": "b916f8bd22dd38b4807298a4c935f6bf2969eb13",
        "source_tree": "71f8994c8e8e8f10c09cf8aef3e21ba3635d627e",
        "source_dirty": False,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "capability_registry_sha256": skill_hashes["capability_registry_sha256"],
        "charter_sha256": skill_hashes["charter_sha256"],
        "dockerfile_sha256": skill_hashes["dockerfile_sha256"],
        "entrypoint_sha256": skill_hashes["entrypoint_sha256"],
        "meta_sha256": skill_hashes["meta_sha256"],
        "output_schema_sha256": skill_hashes["output_schema_sha256"],
        "runtime_lock_sha256": skill_hashes["runtime_lock_sha256"],
        "skill_invoker_sha256": skill_hashes["skill_invoker_sha256"],
        "skill_md_sha256": skill_hashes["skill_md_sha256"],
    }
    manifest = {
        "schema_version": module.LEGACY_RELEASE_SCHEMA,
        "release_id": release_id,
        "created_at": "2026-07-29T07:40:23.273627Z",
        "generic_worker_route_allowed": False,
        "image_entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
        "image_id": "sha256:" + image_character * 64,
        "image_labels": {
            "io.xinao.researcher.chain": "dedicated-xinao-science",
            "io.xinao.researcher.generic-worker-route": "forbidden",
            "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        },
        "image_tag_observational": f"xinao-researcher:{release_id}",
        "run_namespace": "xinao_researcher",
        "skill_hashes": skill_hashes,
        "source_identity": source_identity,
        "state_namespace": "xinao_skill/researcher_container",
    }
    release_dir = state / "researcher_container" / "releases" / release_id
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = release_dir / "release.json"
    module._write_json_atomic(manifest_path, manifest, create_new=True)
    # Pure v1 directory: only release.json.
    assert sorted(path.name for path in release_dir.iterdir()) == ["release.json"]
    return manifest, manifest_path, rendering


def _install_drifted_skill(
    module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, active_rendering: Path
) -> Path:
    installed = tmp_path / "installed_skill"
    _copy_skill_tree(active_rendering, installed, newline=None)
    # Drift three sealed Skill files relative to active CRLF bundle.
    (installed / "SKILL.md").write_bytes(
        (installed / "SKILL.md").read_bytes() + b"\n# installed-drift\n"
    )
    capabilities = installed / "references" / "capabilities.v1.json"
    capabilities.write_bytes(capabilities.read_bytes().rstrip() + b"\n")
    meta = installed / "references" / "meta.md"
    meta.write_bytes(meta.read_bytes() + b"\ninstalled-meta-drift\n")
    cache_root = installed / "scripts" / "__pycache__"
    cache_root.mkdir()
    (cache_root / "xinao.cpython-312.pyc").write_bytes(b"xinao-live-cache-v1\x00\x01\x02\n")
    (cache_root / "empty-cache-dir").mkdir()
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(module, "DEFAULT_INSTALLED_SKILL_ROOT", installed)
    return installed


def _legacy_pointer_for_v1(
    module,
    active: dict[str, object],
    active_path: Path,
    previous: dict[str, object],
    previous_path: Path,
) -> dict[str, object]:
    return {
        "schema_version": module.LEGACY_POINTER_SCHEMA,
        "release_id": active["release_id"],
        "release_manifest_path": str(active_path),
        "release_manifest_sha256": module._sha256(active_path),
        "promoted_at": "2026-07-29T07:40:23.281374Z",
        "previous_pointer_sha256": "d" * 64,
        "previous_release_id": previous["release_id"],
        "previous_release_manifest_path": str(previous_path),
        "previous_release_manifest_sha256": module._sha256(previous_path),
    }


def _prepare_v1_migration_world(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    active_newline: bytes = b"\r\n",
    previous_newline: bytes = b"\n",
) -> dict[str, object]:
    previous, previous_path, previous_rendering = _write_pure_v1_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        newline=previous_newline,
        marker=b"previous-rendering\n",
        release_suffix="4d3458d9901c09b1",
    )
    active, active_path, active_rendering = _write_pure_v1_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="b",
        newline=active_newline,
        marker=b"active-rendering\n",
        release_suffix="0a7aea3f2ed52581",
    )
    installed = _install_drifted_skill(
        module, tmp_path, monkeypatch, active_rendering=active_rendering
    )
    pointer_path = module._state_paths()["pointer"]
    legacy = _legacy_pointer_for_v1(module, active, active_path, previous, previous_path)
    module._write_json_atomic(pointer_path, legacy)
    target, target_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="c",
        variant=b"migration-current-target\n",
    )
    monkeypatch.setattr(
        module,
        "_prepare_migration_target",
        lambda: (target, target_path),
    )
    return {
        "active": active,
        "active_path": active_path,
        "active_rendering": active_rendering,
        "previous": previous,
        "previous_path": previous_path,
        "previous_rendering": previous_rendering,
        "installed": installed,
        "pointer_path": pointer_path,
        "legacy": legacy,
        "legacy_bytes": pointer_path.read_bytes(),
        "target": target,
        "target_path": target_path,
        "installed_snapshot": {
            relative.as_posix(): (installed / relative).read_bytes()
            for relative in [
                path.relative_to(installed) for path in installed.rglob("*") if path.is_file()
            ]
        },
        "installed_directories": sorted(
            path.relative_to(installed).as_posix() for path in installed.rglob("*") if path.is_dir()
        ),
    }


def _run_installed_xinao(
    module, world: dict[str, object], *arguments: str
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["XINAO_SKILL_STATE_ROOT"] = str(module._state_paths()["state_root"])
    environment["XINAO_INSTALLED_SKILL_ROOT"] = str(world["installed"])
    environment["XINAO_RESEARCH_RUN_ROOT"] = str(module._state_paths()["state_root"] / "test-runs")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(Path(world["installed"]) / "scripts" / "xinao.py"),
            *arguments,
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )


def _json_stdout(completed: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    assert completed.stdout, completed.stderr.decode("utf-8", errors="replace")
    return json.loads(completed.stdout.decode("utf-8").strip().splitlines()[-1])


def test_real_b916_fresh_inspect_and_dual_protocol_v1_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    before = _run_installed_xinao(module, world, "inspect")
    assert before.returncode == 0
    assert before.stderr == b""
    baseline = _json_stdout(before)
    assert baseline["schema_version"] == "xinao.skill_inspection.v1"
    assert baseline["runtime_status"] == "AVAILABLE"
    assert baseline["release_id"] == "researcher-1.0.0-0a7aea3f2ed52581"

    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )

    def crash_after_new_launcher(phase: str, relative: str) -> None:
        if phase == "forward:after-replace" and relative == "scripts/xinao.py":
            raise module.XinaoError("INJECTED_CRASH", "new launcher over v1 pointer")

    monkeypatch.setattr(module, "_projection_fault_point", crash_after_new_launcher)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "INJECTED_CRASH"
    journal, _journal_path = module._pending_journals()[0]
    assert journal["state"] == "PREPARED"
    assert module._load_json(world["pointer_path"])["schema_version"] == (
        module.LEGACY_POINTER_SCHEMA
    )
    fallback = _run_installed_xinao(module, world, "inspect")
    assert fallback.returncode == 0
    assert fallback.stderr == b""
    assert _json_stdout(fallback) == baseline

    monkeypatch.setattr(module, "_projection_fault_point", lambda _phase, _relative: None)
    recovered = module.recover_migration_transaction(str(journal["txn_id"]))
    assert recovered["status"] == "MIGRATED"


def test_installed_canary_handoff_runs_while_runtime_parent_holds_activation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)

    def stop_after_canary_started(_journal):
        raise KeyboardInterrupt("leave the real pending canary state")

    monkeypatch.setattr(module, "_run_activation_canary", stop_after_canary_started)
    with pytest.raises(KeyboardInterrupt):
        module.bootstrap_migrate()
    journal, _journal_path = module._pending_journals()[0]
    assert journal["state"] == "CANARY_STARTED"

    with module._activation_lock():
        completed = _run_installed_xinao(
            module, world, "_canary", "--txn-id", str(journal["txn_id"])
        )

    canary = _json_stdout(completed)
    assert "ACTIVATION_LOCK_TIMEOUT" not in canary.get("reason_codes", [])
    if completed.returncode == 0:
        assert canary["status"] == "CANARY_READY"
        assert canary["txn_id"] == journal["txn_id"]
    else:
        # The synthetic image identity may fail the real Docker activation gate;
        # reaching that gate proves the launcher crossed the parent-held lock.
        assert canary["status"] == "PREFLIGHT_FAILED"


def test_thin_launcher_ordinary_command_still_acquires_activation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    bootstrap = _bootstrap_module()
    state_root = tmp_path / "state"
    (state_root / "researcher_container").mkdir(parents=True)
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(state_root))
    calls: list[Path] = []

    @contextmanager
    def lock_witness(observed_root: Path):
        calls.append(observed_root)
        raise bootstrap.BootstrapError("LOCK_WITNESS", str(observed_root))
        yield

    monkeypatch.setattr(bootstrap, "_activation_lock", lock_witness)
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._run_runtime(["inspect"])
    assert failure.value.reason_code == "LOCK_WITNESS"
    assert calls == [state_root]


def test_bootstrap_migrate_success_from_pure_v1_and_crlf_lf_renderings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    # Active rendering is CRLF; previous is LF — commit identity alone is insufficient.
    active_skill_md = (world["active_rendering"] / "SKILL.md").read_bytes()
    previous_skill_md = (world["previous_rendering"] / "SKILL.md").read_bytes()
    assert b"\r\n" in active_skill_md
    assert b"\r\n" not in previous_skill_md
    assert (
        world["active"]["source_identity"]["source_commit"]
        == (world["previous"]["source_identity"]["source_commit"])
    )
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "MIGRATED"
    assert receipt["completion_claim_allowed"] is False
    assert receipt["pointer_generation"] == 1
    assert "legacy_restore_tree_sha256" in receipt
    pointer = module._load_json(world["pointer_path"])
    assert pointer["schema_version"] == module.CURRENT_POINTER_SCHEMA
    assert pointer["generation"] == 1
    # The active target is a real current v2 build; historical v1 images remain restore-only.
    assert pointer["active"]["release_id"] == world["target"]["release_id"]
    assert (
        module._state_paths()["release_root"] / pointer["active"]["release_id"] / "skill-bundle"
    ).is_dir()
    assert pointer["previous_verified"] is None
    # Original pure v1 directories remain reconstructible (only release.json).
    assert sorted(
        path.name
        for path in (
            module._state_paths()["release_root"] / world["active"]["release_id"]
        ).iterdir()
    ) == ["release.json"]
    journal = module._load_json(module._journal_path(pointer["active"]["activation_txn_id"]))
    assert journal["operation"] == "MIGRATE"
    assert journal["state"] == "VERIFIED"
    assert journal["from"]["legacy_restore_tree_sha256"] == receipt["legacy_restore_tree_sha256"]
    assert not (world["installed"] / "scripts" / "__pycache__").exists()
    restore_root = Path(journal["from"]["legacy_restore_path"]) / "installed_skill"
    assert (
        restore_root / "scripts" / "__pycache__" / "xinao.cpython-312.pyc"
    ).read_bytes() == b"xinao-live-cache-v1\x00\x01\x02\n"
    assert (restore_root / "scripts" / "__pycache__" / "empty-cache-dir").is_dir()
    context = module._load_current_context(require_terminal=True)
    assert context["release"]["required_bootstrap_protocol"] == 2


def test_prepare_migration_target_builds_current_release_under_legacy_pointer_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    prepare = module._prepare_migration_target
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "_prepare_migration_target", prepare)
    monkeypatch.setattr(module, "_migration_source_root", lambda: ROOT)
    calls: list[dict[str, object]] = []

    def fake_build(source_root: Path, *, allow_dirty: bool, migration_legacy_pointer_sha256=None):
        calls.append(
            {
                "source_root": source_root,
                "allow_dirty": allow_dirty,
                "legacy_pointer_sha256": migration_legacy_pointer_sha256,
            }
        )
        return {
            "release_id": world["target"]["release_id"],
            "release_manifest_path": str(world["target_path"]),
            "release_manifest_sha256": module._sha256(world["target_path"]),
        }

    monkeypatch.setattr(module, "build_release", fake_build)
    before = world["pointer_path"].read_bytes()
    prepared = module._prepare_migration_target()

    assert prepared == (world["target"], world["target_path"])
    assert calls == [
        {
            "source_root": ROOT,
            "allow_dirty": False,
            "legacy_pointer_sha256": hashlib.sha256(before).hexdigest(),
        }
    ]
    assert world["pointer_path"].read_bytes() == before


def test_bootstrap_migrate_ignores_corrupt_test_only_source_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    rendering = Path(world["active_rendering"])
    (rendering / "SKILL.md").write_bytes(b"foreign source rendering\n")
    (rendering / "unknown-extra.bin").write_bytes(b"ignored\n")
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    result = module.bootstrap_migrate()
    assert result["status"] == "MIGRATED"


def test_bootstrap_migrate_captures_exact_drifted_live_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    receipt = module.bootstrap_migrate()
    journal = module._load_json(module._journal_path(receipt["txn_id"]))
    restore_root = Path(journal["from"]["legacy_restore_path"])
    restored_skill = restore_root / "installed_skill"
    for relative, payload in world["installed_snapshot"].items():
        assert (restored_skill / relative).read_bytes() == payload
    # Drifted files must not equal the active historical rendering.
    assert (restored_skill / "SKILL.md").read_bytes() != (
        world["active_rendering"] / "SKILL.md"
    ).read_bytes()


def test_bootstrap_migrate_ignores_missing_test_only_previous_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    import shutil

    shutil.rmtree(Path(world["previous_rendering"]))
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    result = module.bootstrap_migrate()
    assert result["status"] == "MIGRATED"


def test_bootstrap_migrate_corrupt_v1_manifest_zero_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    world["active_path"].write_text("{not-json", encoding="utf-8")
    before = world["pointer_path"].read_bytes()
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code in {
        "JSON_READ_FAILED",
        "RELEASE_MANIFEST_IDENTITY_MISMATCH",
        "MIGRATION_RELEASE_INCOMPLETE",
    }
    assert world["pointer_path"].read_bytes() == before


def test_bootstrap_migrate_pointer_cas_conflict_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    pointer_path = world["pointer_path"]
    original_switch = module._switch_migrate_pointer

    def drift_then_switch(journal, journal_path):
        drifted = module._load_json(pointer_path)
        drifted["promoted_at"] = "2026-07-30T00:00:00Z"
        module._write_json_atomic(pointer_path, drifted)
        return original_switch(journal, journal_path)

    monkeypatch.setattr(module, "_switch_migrate_pointer", drift_then_switch)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "CURRENT_POINTER_CAS_CONFLICT"
    assert module._load_json(pointer_path)["schema_version"] == module.LEGACY_POINTER_SCHEMA
    pending = module._pending_journals()
    assert len(pending) == 1
    assert pending[0][0]["operation"] == "MIGRATE"
    assert pending[0][0]["state"] == "PREPARED"


def test_bootstrap_migrate_repeated_invocation_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    first = module.bootstrap_migrate()
    pointer_after = world["pointer_path"].read_bytes()
    journal_path = module._journal_path(first["txn_id"])
    journal_after = journal_path.read_bytes()
    second = module.bootstrap_migrate()
    assert first["status"] == "MIGRATED"
    assert second["status"] == "ALREADY_MIGRATED"
    assert world["pointer_path"].read_bytes() == pointer_after
    assert journal_path.read_bytes() == journal_after


def test_bootstrap_migrate_interrupted_prepared_boundary_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    pointer_path = world["pointer_path"]
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    original_continue = module._continue_migrate_journal
    calls = {"count": 0}

    def stop_after_prepare(journal, journal_path):
        calls["count"] += 1
        if calls["count"] == 1:
            assert journal["state"] == "PREPARED"
            assert module._load_json(pointer_path)["schema_version"] == module.LEGACY_POINTER_SCHEMA
            raise module.XinaoError("INJECTED_CRASH", "prepared boundary")
        return original_continue(journal, journal_path)

    monkeypatch.setattr(module, "_continue_migrate_journal", stop_after_prepare)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "INJECTED_CRASH"
    pending = module._pending_journals()
    assert len(pending) == 1
    assert pending[0][0]["state"] == "PREPARED"
    monkeypatch.setattr(module, "_continue_migrate_journal", original_continue)
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "MIGRATED"
    pointer = module._load_json(pointer_path)
    assert pointer["schema_version"] == module.CURRENT_POINTER_SCHEMA
    journal = module._load_json(module._journal_path(pointer["active"]["activation_txn_id"]))
    assert journal["state"] == "VERIFIED"
    assert not module._pending_journals()


def test_bootstrap_migrate_crash_after_pointer_switch_recovers_or_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    installed = world["installed"]
    installed_before = {
        path.relative_to(installed).as_posix(): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    legacy_bytes = world["legacy_bytes"]

    def fail_canary(journal):
        raise module.XinaoError("INJECTED_CANARY_FAILURE", "post-switch")

    monkeypatch.setattr(module, "_run_activation_canary", fail_canary)
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "ROLLED_BACK"
    assert world["pointer_path"].read_bytes() == legacy_bytes
    assert (
        module._load_json(world["pointer_path"])["schema_version"] == module.LEGACY_POINTER_SCHEMA
    )
    assert {
        path.relative_to(installed).as_posix(): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    } == installed_before
    # Pure v1 release directories restored.
    assert sorted(
        path.name
        for path in (
            module._state_paths()["release_root"] / world["active"]["release_id"]
        ).iterdir()
    ) == ["release.json"]


def test_bootstrap_migrate_crash_after_pointer_switch_then_recover_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POINTER_SWITCHED crash must leave recoverable journal that can finish v2 activation."""

    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    original_switch = module._switch_migrate_pointer
    calls = {"count": 0}

    def switch_then_crash(journal, journal_path):
        calls["count"] += 1
        switched = original_switch(journal, journal_path)
        if calls["count"] == 1:
            raise module.XinaoError("INJECTED_CRASH", "after pointer switch")
        return switched

    monkeypatch.setattr(module, "_switch_migrate_pointer", switch_then_crash)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "INJECTED_CRASH"
    pending = module._pending_journals()
    assert len(pending) == 1
    assert pending[0][0]["operation"] == "MIGRATE"
    assert pending[0][0]["state"] == "POINTER_SWITCHED"
    assert (
        module._load_json(world["pointer_path"])["schema_version"] == module.CURRENT_POINTER_SCHEMA
    )
    monkeypatch.setattr(module, "_switch_migrate_pointer", original_switch)
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "MIGRATED"
    journal = module._load_json(module._journal_path(receipt["txn_id"]))
    assert journal["state"] == "VERIFIED"
    assert not module._pending_journals()


def test_bootstrap_migrate_cli_absorbs_technical_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    exit_code = module.main(["bootstrap-migrate"])
    assert exit_code == 0
    assert (
        module._load_json(world["pointer_path"])["schema_version"] == module.CURRENT_POINTER_SCHEMA
    )
    exit_code = module.main(
        ["bootstrap-migrate", "--compat-release", str(world["active"]["release_id"])]
    )
    assert exit_code == 2


def test_bootstrap_migrate_companion_runtime_tamper_fails_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap = _bootstrap_module()
    runtime_path = bootstrap._companion_runtime_path()
    original = runtime_path.read_bytes()
    try:
        runtime_path.write_bytes(original + b"\n# tampered\n")
        with pytest.raises(bootstrap.BootstrapError) as failure:
            bootstrap._run_companion_runtime(["bootstrap-migrate"])
        assert failure.value.reason_code == "COMPANION_RUNTIME_IDENTITY_MISMATCH"
    finally:
        runtime_path.write_bytes(original)


def test_bootstrap_companion_runtime_seal_matches_repository_bytes() -> None:
    bootstrap = _bootstrap_module()
    runtime_path = bootstrap._companion_runtime_path()

    assert hashlib.sha256(runtime_path.read_bytes()).hexdigest() == (
        bootstrap.EXPECTED_COMPANION_RUNTIME_SHA256
    )


def test_bootstrap_migrate_concurrent_second_lock_holder_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    # Simulate OS lock contention with a non-reentrant hold (portable across FS).
    from contextlib import contextmanager

    gate = threading.Lock()
    ready = threading.Event()
    release = threading.Event()

    @contextmanager
    def contended_lock():
        if not gate.acquire(blocking=False):
            raise module.XinaoError("ACTIVATION_LOCK_TIMEOUT", "contended")
        try:
            yield
        finally:
            gate.release()

    monkeypatch.setattr(module, "_activation_lock", contended_lock)

    def holder() -> None:
        with module._activation_lock():
            ready.set()
            release.wait(timeout=10)

    worker = threading.Thread(target=holder)
    worker.start()
    assert ready.wait(timeout=5)
    before = world["pointer_path"].read_bytes()
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "ACTIVATION_LOCK_TIMEOUT"
    assert world["pointer_path"].read_bytes() == before
    release.set()
    worker.join(timeout=5)
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "MIGRATED"


def test_bootstrap_migrate_singleflight_builds_once_and_reuses_migration_txn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    original_prepare = module._prepare_migration_target
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "_prepare_migration_target", original_prepare)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    build_started = threading.Event()
    release_build = threading.Event()
    build_calls: list[str] = []
    build_guard = threading.Lock()

    def one_build(_source_root, *, allow_dirty, migration_legacy_pointer_sha256):
        assert allow_dirty is False
        with build_guard:
            build_calls.append(str(migration_legacy_pointer_sha256))
        build_started.set()
        assert release_build.wait(timeout=10)
        return {
            "release_id": world["target"]["release_id"],
            "release_manifest_path": str(world["target_path"]),
            "release_manifest_sha256": module._sha256(world["target_path"]),
        }

    monkeypatch.setattr(module, "build_release", one_build)
    results: list[dict[str, object]] = []
    failures: list[BaseException] = []

    def invoke() -> None:
        try:
            results.append(module.bootstrap_migrate())
        except BaseException as exc:  # pragma: no cover - asserted empty
            failures.append(exc)

    first = threading.Thread(target=invoke)
    second = threading.Thread(target=invoke)
    first.start()
    assert build_started.wait(timeout=10)
    second.start()
    time.sleep(0.1)
    release_build.set()
    first.join(timeout=30)
    second.join(timeout=30)
    assert not first.is_alive() and not second.is_alive()
    assert failures == []
    assert len(build_calls) == 1
    assert {str(result["status"]) for result in results} == {
        "MIGRATED",
        "ALREADY_MIGRATED",
    }
    assert len({str(result["txn_id"]) for result in results}) == 1
    migrate_journals = [
        value
        for value, _path in (
            (
                module._load_json(path),
                path,
            )
            for path in module._state_paths()["transaction_root"].glob("*/activation.v1.json")
        )
        if value.get("operation") == "MIGRATE"
    ]
    assert len(migrate_journals) == 1


def test_migration_bootstrap_lock_serializes_independent_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    state_root = _state(module, tmp_path, monkeypatch)
    child_code = (
        "import importlib.util,time\n"
        f"p={str(SKILL_ROOT / 'scripts' / 'xinao_runtime.py')!r}\n"
        "s=importlib.util.spec_from_file_location('xinao_lock_child',p)\n"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
        "with m._migration_bootstrap_lock():\n"
        " print('READY',flush=True)\n"
        " time.sleep(1.25)\n"
    )
    environment = os.environ.copy()
    environment["XINAO_SKILL_STATE_ROOT"] = str(state_root)
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", child_code],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "READY"
    started = time.monotonic()
    with module._migration_bootstrap_lock():
        elapsed = time.monotonic() - started
    stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, (stdout, stderr)
    assert elapsed >= 0.75


@pytest.mark.parametrize(
    "mutation",
    (
        "hardlinked_launcher",
        "impure_previous_release",
        "corrupt_active_manifest",
        "missing_previous_manifest",
    ),
)
def test_full_v1_preflight_fails_before_build_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    module = _module()
    original_prepare = module._prepare_migration_target
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "_prepare_migration_target", original_prepare)
    if mutation == "hardlinked_launcher":
        os.link(
            world["installed"] / "scripts" / "xinao.py",
            tmp_path / "launcher-hardlink.py",
        )
    elif mutation == "impure_previous_release":
        previous_dir = Path(world["previous_path"]).parent
        (previous_dir / "foreign.bin").write_bytes(b"foreign\n")
    elif mutation == "corrupt_active_manifest":
        Path(world["active_path"]).write_text("{not-json", encoding="utf-8")
    else:
        Path(world["previous_path"]).unlink()
    build_calls = {"count": 0}

    def forbidden_build(*_args, **_kwargs):
        build_calls["count"] += 1
        raise AssertionError("build_release must not run")

    monkeypatch.setattr(module, "build_release", forbidden_build)
    with pytest.raises(module.XinaoError):
        module.bootstrap_migrate()
    assert build_calls["count"] == 0
    transaction_root = module._state_paths()["transaction_root"]
    assert not transaction_root.exists() or not list(transaction_root.glob("*/activation.v1.json"))


def test_killed_c_stage_partial_recovers_through_stable_d_entry_without_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()

    def crash_during_stage_write(phase: str, relative: str) -> None:
        if phase == "rollback-stage:during-partial-write" and relative == "rollback-SKILL.md":
            raise module.XinaoError("INJECTED_KILL", "partial C stage write")

    monkeypatch.setattr(module, "_projection_fault_point", crash_during_stage_write)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "INJECTED_KILL"
    journal = module._load_json(module._journal_path(migrated["txn_id"]))
    assert journal["state"] == "LEGACY_RESTORE_STARTED"
    stable_launcher, stable_pointer = module._stable_recovery_paths()
    assert stable_launcher.is_file() and stable_pointer.is_file()
    rollback_stage = module._projection_stage_root(migrated["txn_id"], "rollback")
    assert any(
        path.name.startswith(module._transaction_partial_prefix(migrated["txn_id"]))
        for path in rollback_stage.rglob("*")
        if path.is_file()
    )

    environment = os.environ.copy()
    environment["XINAO_SKILL_STATE_ROOT"] = str(module._state_paths()["state_root"])
    environment["XINAO_INSTALLED_SKILL_ROOT"] = str(world["installed"])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-I", str(stable_launcher)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert _json_stdout(completed)["status"] == "ROLLED_BACK"
    _assert_full_v1_preimage(module, world)
    assert not stable_pointer.exists()
    assert not module._projection_stage_root(migrated["txn_id"], "forward").exists()
    assert not rollback_stage.exists()
    txn_root = module._journal_path(migrated["txn_id"]).parent
    assert not list(txn_root.rglob(f"{module._transaction_partial_prefix(migrated['txn_id'])}*"))


@pytest.mark.parametrize("tamper", ("same_txn_field", "format_only", "trailing_bytes"))
def test_stable_recovery_pointer_tamper_is_preserved_by_publish_and_retire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()

    def stop_after_pointer_republish(phase: str, relative: str) -> None:
        if phase == "rollback-stage:during-partial-write" and relative == "rollback-SKILL.md":
            raise module.XinaoError("INJECTED_STOP", "stable pointer published")

    monkeypatch.setattr(module, "_projection_fault_point", stop_after_pointer_republish)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError):
        module.rollback_release()
    journal = module._load_json(module._journal_path(migrated["txn_id"]))
    _stable_launcher, stable_pointer = module._stable_recovery_paths()
    expected = stable_pointer.read_bytes()
    value = json.loads(expected)
    assert value["txn_id"] == migrated["txn_id"]
    if tamper == "same_txn_field":
        value["created_at"] = "2099-01-01T00:00:00Z"
        tampered = module._canonical_bytes(value)
    elif tamper == "format_only":
        tampered = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
    else:
        tampered = expected + b"\nforeign"
    assert tampered != expected
    stable_pointer.write_bytes(tampered)

    with pytest.raises(module.XinaoError) as publish_failure:
        module._publish_stable_recovery_entry(journal)
    assert publish_failure.value.reason_code == "STABLE_RECOVERY_POINTER_CONFLICT"
    assert stable_pointer.read_bytes() == tampered
    with pytest.raises(module.XinaoError) as retire_failure:
        module._retire_stable_recovery_pointer(journal)
    assert retire_failure.value.reason_code == "STABLE_RECOVERY_POINTER_CONFLICT"
    assert stable_pointer.read_bytes() == tampered


def test_verified_hygiene_conflict_preserves_v2_projection_and_terminal_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    original_complete = module._complete_canary
    evidence: dict[str, object] = {}

    def complete_then_tamper(journal, journal_path, *, terminal_state):
        result = original_complete(journal, journal_path, terminal_state=terminal_state)
        terminal = result[0]
        assert terminal["state"] == "VERIFIED"
        _stable_launcher, stable_pointer = module._stable_recovery_paths()
        expected = stable_pointer.read_bytes()
        value = json.loads(expected)
        value["created_at"] = "2099-01-01T00:00:00Z"
        tampered = module._canonical_bytes(value)
        stable_pointer.write_bytes(tampered)
        evidence.update(
            {
                "txn_id": terminal["txn_id"],
                "pointer": world["pointer_path"].read_bytes(),
                "installed": {
                    path.relative_to(world["installed"]).as_posix(): path.read_bytes()
                    for path in world["installed"].rglob("*")
                    if path.is_file()
                },
                "tampered": tampered,
            }
        )
        return result

    monkeypatch.setattr(module, "_complete_canary", complete_then_tamper)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "STABLE_RECOVERY_POINTER_CONFLICT"
    txn_id = str(evidence["txn_id"])
    journal = module._load_json(module._journal_path(txn_id))
    assert journal["state"] == "VERIFIED"
    assert world["pointer_path"].read_bytes() == evidence["pointer"]
    assert module._load_json(world["pointer_path"])["schema_version"] == (
        module.CURRENT_POINTER_SCHEMA
    )
    assert {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    } == evidence["installed"]
    _stable_launcher, stable_pointer = module._stable_recovery_paths()
    assert stable_pointer.read_bytes() == evidence["tampered"]


def test_rolled_back_hygiene_conflict_preserves_v1_and_terminal_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    original_prepare = module._prepare_migration_target
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    original_transition = module._journal_transition
    evidence: dict[str, bytes] = {}

    def transition_then_tamper(journal_path, journal, state, **changes):
        transitioned = original_transition(journal_path, journal, state, **changes)
        if state == "ROLLED_BACK" and journal.get("operation") == "MIGRATE":
            _stable_launcher, stable_pointer = module._stable_recovery_paths()
            tampered = stable_pointer.read_bytes() + b"\nforeign"
            stable_pointer.write_bytes(tampered)
            evidence["tampered"] = tampered
        return transitioned

    monkeypatch.setattr(module, "_journal_transition", transition_then_tamper)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "STABLE_RECOVERY_POINTER_CONFLICT"
    assert module._load_json(module._journal_path(migrated["txn_id"]))["state"] == ("ROLLED_BACK")
    _assert_full_v1_preimage(module, world)
    _stable_launcher, stable_pointer = module._stable_recovery_paths()
    assert stable_pointer.read_bytes() == evidence["tampered"]

    # A subsequent migrate attempt must resolve terminal hygiene before any
    # release build or new transaction. Foreign same-transaction bytes remain
    # evidence and fail closed instead of silently starting a remigration.
    monkeypatch.setattr(module, "_journal_transition", original_transition)
    monkeypatch.setattr(module, "_prepare_migration_target", original_prepare)
    transaction_root = module._state_paths()["transaction_root"]
    transaction_ids_before = sorted(
        path.name for path in transaction_root.iterdir() if path.is_dir()
    )
    foreign_before = stable_pointer.read_bytes()
    build_calls = 0

    def forbidden_build(*_args, **_kwargs):
        nonlocal build_calls
        build_calls += 1
        raise AssertionError("foreign terminal recovery pointer must fail before build")

    monkeypatch.setattr(module, "build_release", forbidden_build)
    with pytest.raises(module.XinaoError) as remigration_failure:
        module.bootstrap_migrate()
    assert remigration_failure.value.reason_code == "STABLE_RECOVERY_POINTER_CONFLICT"
    assert build_calls == 0
    assert sorted(path.name for path in transaction_root.iterdir() if path.is_dir()) == (
        transaction_ids_before
    )
    assert stable_pointer.read_bytes() == foreign_before
    assert module._load_json(module._journal_path(migrated["txn_id"]))["state"] == ("ROLLED_BACK")
    _assert_full_v1_preimage(module, world)


def test_terminal_hygiene_uses_pointer_txn_when_rollbacks_share_legacy_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    original_prepare = module._prepare_migration_target
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )

    first = module.bootstrap_migrate()
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    first_rollback = module.rollback_release()
    assert first_rollback["status"] == "ROLLED_BACK"
    legacy_sha256 = module._sha256(world["pointer_path"])

    second = module.bootstrap_migrate()
    original_retire = module._retire_stable_recovery_pointer

    def preserve_latest_pointer(journal):
        if journal.get("txn_id") == second["txn_id"]:
            raise module.XinaoError("INJECTED_STOP", "leave exact terminal pointer")
        return original_retire(journal)

    monkeypatch.setattr(module, "_retire_stable_recovery_pointer", preserve_latest_pointer)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as stopped:
        module.rollback_release()
    assert stopped.value.reason_code == "INJECTED_STOP"

    first_journal = module._load_json(module._journal_path(first["txn_id"]))
    second_journal = module._load_json(module._journal_path(second["txn_id"]))
    assert first_journal["state"] == second_journal["state"] == "ROLLED_BACK"
    assert first_journal["from"]["legacy_pointer_sha256"] == legacy_sha256
    assert second_journal["from"]["legacy_pointer_sha256"] == legacy_sha256
    _stable_launcher, stable_pointer = module._stable_recovery_paths()
    assert stable_pointer.read_bytes() == module._stable_recovery_pointer_payload(second_journal)

    monkeypatch.setattr(module, "_retire_stable_recovery_pointer", original_retire)
    build_calls = 0

    def stop_at_build(*_args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        assert kwargs["migration_legacy_pointer_sha256"] == legacy_sha256
        raise module.XinaoError("INJECTED_BUILD_STOP", "terminal hygiene completed")

    monkeypatch.setattr(module, "build_release", stop_at_build)
    with pytest.raises(module.XinaoError) as build_stop:
        original_prepare()
    assert build_stop.value.reason_code == "INJECTED_BUILD_STOP"
    assert build_calls == 1
    assert not stable_pointer.exists()
    _assert_full_v1_preimage(module, world)


def test_killed_d_cone_partial_is_rebuilt_only_from_bound_transaction_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )

    def crash_during_cone_write(phase: str, _relative: str) -> None:
        if phase == "recovery-cone:during-partial-write":
            raise module.XinaoError("INJECTED_KILL", "partial D cone write")

    monkeypatch.setattr(module, "_projection_fault_point", crash_during_cone_write)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "INJECTED_KILL"
    journal, _path = module._pending_journals()[0]
    txn_id = str(journal["txn_id"])
    cone_stage = module._recovery_cone_stage_root(txn_id)
    assert cone_stage.is_dir()
    assert list(cone_stage.rglob(f"{module._transaction_partial_prefix(txn_id)}*"))

    monkeypatch.setattr(module, "_projection_fault_point", lambda _phase, _relative: None)
    recovered = module.bootstrap_migrate()
    assert recovered["status"] == "MIGRATED"
    assert recovered["txn_id"] == txn_id
    assert not cone_stage.exists()
    assert not list(
        module._journal_path(txn_id).parent.rglob(f"{module._transaction_partial_prefix(txn_id)}*")
    )


def test_foreign_installed_extra_is_preserved_and_blocks_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    module.bootstrap_migrate()
    foreign = world["installed"] / "scripts" / "__pycache__" / "foreign.pyc"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"foreign-after-seal\n")
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "INSTALL_PROJECTION_FOREIGN_ENTRY"
    assert foreign.read_bytes() == b"foreign-after-seal\n"


def _installed_tree_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _active_skill_bundle_map(module, release: dict[str, object]) -> dict[str, bytes]:
    bundle_root = Path(str(release["skill_bundle_path"]))
    files, _directories = module._strict_plain_tree(
        bundle_root, reason_code="INSTALL_PROJECTION_TARGET_INVALID"
    )
    return dict(sorted(files.items()))


def test_already_migrated_uses_original_projection_after_later_activate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    installed_after_migrate = _installed_tree_map(Path(world["installed"]))
    later, _later_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="d",
        variant=b"later-v2-activate\n",
    )
    _install_bootstrap_fence(
        module,
        monkeypatch,
        ["activate", "--release-id", str(later["release_id"])],
    )
    activated = module.activate_release(str(later["release_id"]))
    assert activated["status"] == "VERIFIED"
    assert _installed_tree_map(Path(world["installed"])) == installed_after_migrate
    alignment = module._installed_projection_alignment(later)
    assert alignment["status"] == "DRIFTED"
    _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    monkeypatch.setattr(module, "_validate_release_image_identity", lambda _release: "docker")
    monkeypatch.setattr(
        module,
        "_validate_release_for_invoke",
        lambda _release: (_ for _ in ()).throw(
            module.XinaoError("EGRESS_LIVE_SEAL_MISSING", "expected after activate")
        ),
    )
    drifted_inspect = module.inspect_capability()
    assert drifted_inspect["installed_projection"]["status"] == "DRIFTED"
    assert drifted_inspect["runtime_status"] == "INSTALLED_PROJECTION_DRIFTED"
    assert drifted_inspect["shadow"]["runtime_status"] == "PROJECTION_DRIFTED"
    repeated = module.bootstrap_migrate()
    assert repeated["status"] == "ALREADY_MIGRATED"
    assert repeated["txn_id"] == migrated["txn_id"]
    assert repeated["release_id"] == later["release_id"]
    assert _installed_tree_map(Path(world["installed"])) == installed_after_migrate
    pointer_before = module._state_paths()["pointer"].read_bytes()
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    synced = module.sync_projection()
    assert synced["status"] == "SYNCED"
    assert synced["release_id"] == later["release_id"]
    assert module._state_paths()["pointer"].read_bytes() == pointer_before
    assert _installed_tree_map(Path(world["installed"])) == _active_skill_bundle_map(module, later)
    assert module._installed_projection_alignment(later)["status"] == "ALIGNED"
    _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    aligned_inspect = module.inspect_capability()
    assert aligned_inspect["installed_projection"]["status"] == "ALIGNED"
    assert aligned_inspect["shadow"]["runtime_status"] == "AVAILABLE"
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    again = module.sync_projection()
    assert again["status"] == "ALREADY_ALIGNED"
    assert again["txn_id"] is None


def test_build_release_pre_docker_fence_uses_legacy_pointer_under_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration builds must not require v2 bootstrap fence before docker build."""

    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    legacy_sha = hashlib.sha256(world["legacy_bytes"]).hexdigest()
    env = _fake_build_environment(module, monkeypatch, dirty=False)
    legacy_calls: list[str] = []
    bootstrap_calls: list[str] = []
    original_legacy = module._validate_legacy_build_fence_locked

    def track_legacy(expected_pointer_sha256: str):
        legacy_calls.append(expected_pointer_sha256)
        return original_legacy(expected_pointer_sha256)

    def forbid_bootstrap(command: str, *, expected=None):
        bootstrap_calls.append(command)
        raise module.XinaoError("BOOTSTRAP_FENCE_REQUIRED", "migration must not use v2 fence")

    monkeypatch.setattr(module, "_validate_legacy_build_fence_locked", track_legacy)
    monkeypatch.setattr(module, "_validate_bootstrap_fence_locked", forbid_bootstrap)
    # Stop at docker build after pre-docker fence revalidation succeeds.
    original_run = module._run

    def run_and_stop(arguments, **kwargs):
        command = [str(item) for item in arguments]
        if len(command) >= 2 and command[0] == "docker" and command[1] == "build":
            raise module.XinaoError("INJECTED_STOP_AFTER_PRE_DOCKER_FENCE", "ok")
        return original_run(arguments, **kwargs)

    monkeypatch.setattr(module, "_run", run_and_stop)
    monkeypatch.delenv("XINAO_BOOTSTRAP_FENCE_V1", raising=False)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(
            ROOT,
            allow_dirty=False,
            migration_legacy_pointer_sha256=legacy_sha,
        )
    assert failure.value.reason_code == "INJECTED_STOP_AFTER_PRE_DOCKER_FENCE"
    assert bootstrap_calls == []
    # Start fence + pre-docker fence both re-hold the exact legacy pointer sha.
    assert legacy_calls == [legacy_sha, legacy_sha]
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]
    assert env["live_containers"] == {}


def test_construct_protocol2_release_from_legacy_is_retired_hard_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as failure:
        module._construct_protocol2_release_from_legacy(
            world["active"],
            source_rows=[],
            source_root=world["active_rendering"],
            activation_seed="attack",
        )
    assert failure.value.reason_code == "LEGACY_PROTOCOL2_CONSTRUCT_RETIRED"
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]


def test_apply_legacy_restore_rejects_path_escape_outside_owned_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    # Capture a real restore bundle via a successful prepare then abort before switch.
    original_continue = module._continue_migrate_journal

    def stop_prepared(journal, journal_path):
        assert journal["state"] == "PREPARED"
        raise module.XinaoError("INJECTED_STOP", "hold restore")

    monkeypatch.setattr(module, "_continue_migrate_journal", stop_prepared)
    with pytest.raises(module.XinaoError):
        module.bootstrap_migrate()
    pending = module._pending_journals()
    assert len(pending) == 1
    journal = pending[0][0]
    restore_root = Path(journal["from"]["legacy_restore_path"])
    restore_manifest = module._verify_legacy_restore_bundle(
        restore_root,
        expected_manifest_sha256=journal["from"]["legacy_restore_manifest_sha256"],
        expected_tree_sha256=journal["from"]["legacy_restore_tree_sha256"],
        expected_txn_id=str(journal["txn_id"]),
    )
    # Retarget sealed install path outside the live install root; must fail closed.
    hostile = dict(restore_manifest)
    hostile["installed_skill_root"] = str(tmp_path / "not-the-install-root" / "xinao")
    with pytest.raises(module.XinaoError) as failure:
        module._apply_legacy_restore_bundle(journal, restore_root, hostile)
    assert failure.value.reason_code == "LEGACY_RESTORE_PATH_INVALID"
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]
    monkeypatch.setattr(module, "_continue_migrate_journal", original_continue)


def test_migrate_journal_rejects_foreign_absolute_restore_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )

    def stop_prepared(journal, journal_path):
        assert journal["state"] == "PREPARED"
        raise module.XinaoError("INJECTED_STOP", "hold restore")

    monkeypatch.setattr(module, "_continue_migrate_journal", stop_prepared)
    with pytest.raises(module.XinaoError):
        module.bootstrap_migrate()
    journal, journal_path = module._pending_journals()[0]
    foreign = tmp_path / "foreign_restore"
    foreign.mkdir()
    hostile = dict(journal)
    hostile_from = dict(journal["from"])
    hostile_from["legacy_restore_path"] = str(foreign)
    hostile["from"] = hostile_from
    with pytest.raises(module.XinaoError) as failure:
        module._validate_journal(hostile, journal_path)
    assert failure.value.reason_code == "LEGACY_RESTORE_PATH_INVALID"
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]


def test_reject_crlf_source_bytes_for_build_identity() -> None:
    module = _module()
    with pytest.raises(module.XinaoError) as failure:
        module._reject_crlf_source_bytes(
            "entrypoint",
            Path("docker/xinao-researcher/entrypoint.py"),
            b"print('x')\r\n",
        )
    assert failure.value.reason_code == "SOURCE_CRLF_FORBIDDEN"


def test_post_success_migrate_rollback_restores_sealed_v1_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After successful MIGRATE, ordinary rollback restores sealed v1 without extra fields."""

    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    assert migrated["status"] == "MIGRATED"
    pointer = module._load_json(world["pointer_path"])
    assert pointer["previous_verified"] is None
    journal = module._load_json(module._journal_path(migrated["txn_id"]))
    assert journal["state"] == "VERIFIED"
    assert Path(journal["from"]["legacy_restore_path"]).is_dir()
    # Ordinary thin-bootstrap fence must form over a terminal MIGRATE journal.
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    assert fence["active_txn_id"] == migrated["txn_id"]
    # Migration projects the exact v2 bundle; rollback re-materializes the sealed capture.
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    receipt = module.rollback_release()
    assert receipt["status"] == "ROLLED_BACK"
    assert receipt["operation"] == "MIGRATE"
    assert receipt["reason_code"] == "REQUESTED_ROLLBACK"
    assert receipt["rollback_trigger"] == "REQUESTED"
    assert receipt["completion_claim_allowed"] is False
    assert receipt["legacy_pointer_sha256"] == journal["from"]["legacy_pointer_sha256"]
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]
    restored_pointer = module._load_json(world["pointer_path"])
    assert restored_pointer["schema_version"] == module.LEGACY_POINTER_SCHEMA
    assert restored_pointer == world["legacy"]
    assert {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    } == world["installed_snapshot"]
    assert (world["installed"] / "scripts" / "__pycache__" / "empty-cache-dir").is_dir()
    # Pure v1 release directories restored (release.json only).
    for release_id in (world["active"]["release_id"], world["previous"]["release_id"]):
        release_dir = module._state_paths()["release_root"] / str(release_id)
        assert sorted(path.name for path in release_dir.iterdir()) == ["release.json"]
    sealed = module._load_json(module._journal_path(migrated["txn_id"]))
    assert sealed["state"] == "ROLLED_BACK"
    assert sealed["failure_reason"]["reason_code"] == "REQUESTED_ROLLBACK"
    assert sealed["terminal_pointer_sha256"] == receipt["current_pointer_sha256"]


def test_post_success_migrate_rollback_rejects_stale_pointer_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    pointer_path = world["pointer_path"]
    before = pointer_path.read_bytes()
    installed_before = {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    }
    original_verify = module._verify_legacy_restore_bundle

    def verify_then_drift(restore_root, *, expected_manifest_sha256, expected_tree_sha256):
        manifest = original_verify(
            restore_root,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_tree_sha256=expected_tree_sha256,
        )
        drifted = module._load_json(pointer_path)
        drifted["switched_at"] = "2099-01-01T00:00:00Z"
        module._write_json_atomic(pointer_path, drifted)
        return manifest

    monkeypatch.setattr(module, "_verify_legacy_restore_bundle", verify_then_drift)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "CURRENT_POINTER_CAS_CONFLICT"
    # Restore must not run after CAS miss; live skill tree stays post-migration.
    assert {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    } == installed_before
    journal = module._load_json(module._journal_path(migrated["txn_id"]))
    assert journal["state"] == "LEGACY_RESTORE_STARTED"
    assert journal["terminal_pointer_sha256"] is None


def test_post_success_migrate_rollback_rejects_stale_or_foreign_journal_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    journal_path = module._journal_path(migrated["txn_id"])
    before_pointer = world["pointer_path"].read_bytes()
    # Fence forms against the healthy terminal MIGRATE witness first.
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    journal = module._load_json(journal_path)
    # Stale terminal hash binding: context refuses ordinary rollback mutation.
    journal["terminal_pointer_sha256"] = "a" * 64
    module._write_json_atomic(journal_path, journal)
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "ACTIVATION_POINTER_BINDING_MISMATCH"
    assert world["pointer_path"].read_bytes() == before_pointer


def test_post_success_migrate_rollback_rejects_restore_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    journal = module._load_json(module._journal_path(migrated["txn_id"]))
    restore_root = Path(journal["from"]["legacy_restore_path"])
    skill_md = restore_root / "installed_skill" / "SKILL.md"
    skill_md.write_bytes(skill_md.read_bytes() + b"\n# tampered-restore\n")
    before_pointer = world["pointer_path"].read_bytes()
    installed_before = {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    }
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "LEGACY_RESTORE_IDENTITY_MISMATCH"
    assert world["pointer_path"].read_bytes() == before_pointer
    assert {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    } == installed_before
    assert (
        module._load_json(module._journal_path(migrated["txn_id"]))["state"]
        == "LEGACY_RESTORE_STARTED"
    )


def test_post_success_migrate_rollback_rejects_foreign_restore_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    journal_path = module._journal_path(migrated["txn_id"])
    journal = module._load_json(journal_path)
    foreign = tmp_path / "foreign_restore"
    # Copy sealed restore out of owned txn directory.
    import shutil

    shutil.copytree(journal["from"]["legacy_restore_path"], foreign)
    journal["from"] = {
        **journal["from"],
        "legacy_restore_path": str(foreign),
    }
    module._write_json_atomic(journal_path, journal)
    before_pointer = world["pointer_path"].read_bytes()
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code in {
        "LEGACY_RESTORE_PATH_INVALID",
        "ACTIVATION_SOURCE_INVALID",
        "ACTIVATION_JOURNAL_SCHEMA_INVALID",
        "BOOTSTRAP_FENCE_MISMATCH",
        "RECOVERY_REQUIRED",
    }
    assert world["pointer_path"].read_bytes() == before_pointer


def test_post_success_migrate_rollback_second_call_is_idempotent_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    first = module.rollback_release()
    assert first["status"] == "ROLLED_BACK"
    assert first["rollback_trigger"] == "REQUESTED"
    restored_pointer = world["pointer_path"].read_bytes()
    restored_skill = {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    }
    journal_after = module._journal_path(migrated["txn_id"]).read_bytes()
    # Second ordinary rollback cannot form a v2 fence over restored v1 pointer.
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code in {
        "BOOTSTRAP_MIGRATION_REQUIRED",
        "BOOTSTRAP_FENCE_REQUIRED",
        "BOOTSTRAP_FENCE_MISMATCH",
        "CURRENT_POINTER_SCHEMA_INVALID",
    }
    assert world["pointer_path"].read_bytes() == restored_pointer
    assert {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    } == restored_skill
    assert module._journal_path(migrated["txn_id"]).read_bytes() == journal_after


def test_post_success_migrate_rollback_preserves_legacy_installed_tree_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    # Capture exact pre-migration installed tree including drifted files.
    expected = dict(world["installed_snapshot"])
    module.bootstrap_migrate()
    # Foreign v2-life bytes are never silently overwritten by rollback.
    foreign = b"post-migrate drift\n"
    (world["installed"] / "SKILL.md").write_bytes(foreign)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "INSTALL_PROJECTION_FOREIGN_BYTES"
    assert (world["installed"] / "SKILL.md").read_bytes() == foreign
    assert expected != {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    }


def test_post_success_migrate_rollback_crash_before_journal_seal_heals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    txn_id = migrated["txn_id"]
    original_transition = module._journal_transition
    calls = {"count": 0}

    def crash_after_restore(journal_path, journal, state, **changes):
        calls["count"] += 1
        if state == "ROLLED_BACK" and journal.get("operation") == "MIGRATE":
            raise module.XinaoError("INJECTED_CRASH", "after restore before journal seal")
        return original_transition(journal_path, journal, state, **changes)

    monkeypatch.setattr(module, "_journal_transition", crash_after_restore)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "INJECTED_CRASH"
    # Live world is operational v1; transaction hygiene remains explicitly pending.
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]
    assert module._load_json(module._journal_path(txn_id))["state"] == "LEGACY_RESTORE_STARTED"
    monkeypatch.setattr(module, "_journal_transition", original_transition)
    # bootstrap-migrate heals the journal seal then can re-enter migration.
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    healed = module.bootstrap_migrate()
    assert healed["status"] == "ROLLED_BACK"
    assert module._load_json(module._journal_path(txn_id))["state"] == "ROLLED_BACK"
    remigrated = module.bootstrap_migrate()
    assert remigrated["status"] == "MIGRATED"


def _assert_full_v1_preimage(module, world: dict[str, object]) -> None:
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]
    assert {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    } == world["installed_snapshot"]
    assert (
        sorted(
            path.relative_to(world["installed"]).as_posix()
            for path in world["installed"].rglob("*")
            if path.is_dir()
        )
        == world["installed_directories"]
    )
    for release_id in (world["active"]["release_id"], world["previous"]["release_id"]):
        release_dir = module._state_paths()["release_root"] / str(release_id)
        assert sorted(path.name for path in release_dir.iterdir()) == ["release.json"]


def test_partial_restore_crash_after_skill_before_pointer_recovers_via_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash after installed Skill mutation, before pointer write, must reapply on next rollback."""

    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    txn_id = migrated["txn_id"]
    pointer_path = world["pointer_path"]
    v2_pointer_bytes = pointer_path.read_bytes()
    original_write = module._write_bytes_atomic

    def crash_before_pointer(path, payload, *, create_new: bool = False):
        if module._paths_equal(Path(path), pointer_path):
            raise module.XinaoError("INJECTED_CRASH", "after skill before pointer")
        return original_write(path, payload, create_new=create_new)

    monkeypatch.setattr(module, "_write_bytes_atomic", crash_before_pointer)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "INJECTED_CRASH"
    # Pointer still v2; skill may already be legacy material; journal unsealed.
    assert pointer_path.read_bytes() == v2_pointer_bytes
    assert module._load_json(module._journal_path(txn_id))["state"] == "LEGACY_RESTORE_STARTED"
    monkeypatch.setattr(module, "_write_bytes_atomic", original_write)
    receipt = module.recover_migration_transaction(txn_id)
    assert receipt["status"] == "ROLLED_BACK"
    assert receipt["completion_claim_allowed"] is False
    _assert_full_v1_preimage(module, world)
    assert module._load_json(module._journal_path(txn_id))["state"] == "ROLLED_BACK"


def test_partial_restore_crash_after_pointer_before_release_cleanup_heals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash after pointer write, before release cleanup, must not seal on pointer alone."""

    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    txn_id = migrated["txn_id"]
    pointer_path = world["pointer_path"]
    release_root = module._state_paths()["release_root"]
    # Keep protocol-2 bundle noise under the migrated active release for impurity.
    dirty_release = release_root / str(world["target"]["release_id"])
    assert (dirty_release / "skill-bundle").exists() or dirty_release.is_dir()
    original_write = module._write_bytes_atomic
    pointer_written = {"done": False}

    def crash_after_pointer_before_releases(path, payload, *, create_new: bool = False):
        target = Path(path)
        if module._paths_equal(target, pointer_path):
            original_write(path, payload, create_new=create_new)
            pointer_written["done"] = True
            raise module.XinaoError("INJECTED_CRASH", "after pointer before releases")
        return original_write(path, payload, create_new=create_new)

    monkeypatch.setattr(module, "_write_bytes_atomic", crash_after_pointer_before_releases)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "INJECTED_CRASH"
    assert pointer_written["done"] is True
    assert pointer_path.read_bytes() == world["legacy_bytes"]
    assert module._load_json(module._journal_path(txn_id))["state"] == "LEGACY_RESTORE_STARTED"
    # Historical pure v1 dirs may still be missing restore cleanup; target may still be v2-shaped.
    monkeypatch.setattr(module, "_write_bytes_atomic", original_write)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    # Heal must reapply + full preimage verify before sealing, then may continue migrate.
    healed = module.bootstrap_migrate()
    assert healed["status"] == "ROLLED_BACK"
    assert module._load_json(module._journal_path(txn_id))["state"] == "ROLLED_BACK"
    remigrated = module.bootstrap_migrate()
    assert remigrated["status"] == "MIGRATED"


def test_partial_restore_crash_after_old_launcher_keeps_v1_operational_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    txn_id = migrated["txn_id"]
    original_fault = module._projection_fault_point

    def crash_after_old_launcher(phase: str, relative: str) -> None:
        if phase == "rollback:after-replace" and relative == "scripts/xinao.py":
            raise module.XinaoError("INJECTED_CRASH", "after old launcher")

    monkeypatch.setattr(module, "_projection_fault_point", crash_after_old_launcher)
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "INJECTED_CRASH"
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]
    assert module._load_json(module._journal_path(txn_id))["state"] == "LEGACY_RESTORE_STARTED"
    assert (world["installed"] / "scripts" / "xinao.py").read_bytes() == world[
        "installed_snapshot"
    ]["scripts/xinao.py"]
    assert (world["installed"] / "scripts" / "xinao_runtime.py").is_file()
    monkeypatch.setattr(module, "_projection_fault_point", original_fault)
    receipt = module.recover_migration_transaction(txn_id)
    assert receipt["status"] == "ROLLED_BACK"
    _assert_full_v1_preimage(module, world)
    sealed = module._load_json(module._journal_path(txn_id))
    assert sealed["state"] == "ROLLED_BACK"
    assert sealed["failure_reason"]["reason_code"] == "REQUESTED_ROLLBACK"


def test_heal_refuses_tampered_restore_bundle_without_false_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    txn_id = migrated["txn_id"]
    journal = module._load_json(module._journal_path(txn_id))
    # Simulate crash after full restore before journal seal.
    restore_root = Path(journal["from"]["legacy_restore_path"])
    restore_manifest = module._verify_legacy_restore_bundle(
        restore_root,
        expected_manifest_sha256=journal["from"]["legacy_restore_manifest_sha256"],
        expected_tree_sha256=journal["from"]["legacy_restore_tree_sha256"],
    )
    module._apply_legacy_restore_bundle(journal, restore_root, restore_manifest)
    assert world["pointer_path"].read_bytes() == world["legacy_bytes"]
    assert module._load_json(module._journal_path(txn_id))["state"] == "VERIFIED"
    # Tamper sealed restore after live apply; heal must fail closed (no false ROLLED_BACK).
    skill_md = restore_root / "installed_skill" / "SKILL.md"
    skill_md.write_bytes(skill_md.read_bytes() + b"\n# foreign-or-tampered\n")
    # Also dirty one live release so reapply would be required if bundle were intact.
    dirty = module._state_paths()["release_root"] / str(world["active"]["release_id"]) / "extra.bin"
    dirty.write_bytes(b"impure\n")
    with pytest.raises(module.XinaoError) as failure:
        module._heal_restored_migrate_journal_if_needed(module._sha256(world["pointer_path"]))
    assert failure.value.reason_code in {
        "RECOVERY_REQUIRED",
        "RECOVERY_CONFLICT",
        "LEGACY_RESTORE_PATH_INVALID",
    }
    assert module._load_json(module._journal_path(txn_id))["state"] == "VERIFIED"
    # bootstrap_migrate must not start a new migration over the conflicted witness.
    with pytest.raises(module.XinaoError) as migrate_failure:
        module.bootstrap_migrate()
    assert migrate_failure.value.reason_code in {"RECOVERY_REQUIRED", "RECOVERY_CONFLICT"}
    assert module._load_json(module._journal_path(txn_id))["state"] == "VERIFIED"
    pending = [item for item in module._pending_journals() if item[0].get("operation") == "MIGRATE"]
    assert pending == []


def test_heal_ambiguous_matching_verified_migrate_journals_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    txn_id = migrated["txn_id"]
    journal_path = module._journal_path(txn_id)
    journal = module._load_json(journal_path)
    restore_root = Path(journal["from"]["legacy_restore_path"])
    # Apply full restore without sealing journal (simulates complete apply + seal crash).
    restore_manifest = module._verify_legacy_restore_bundle(
        restore_root,
        expected_manifest_sha256=journal["from"]["legacy_restore_manifest_sha256"],
        expected_tree_sha256=journal["from"]["legacy_restore_tree_sha256"],
    )
    module._apply_legacy_restore_bundle(journal, restore_root, restore_manifest)
    # Forge a second matching VERIFIED MIGRATE witness with its own sealed restore copy.
    import shutil

    second_txn = "xra_20990101T000000_aaaaaaaaaaaaaaaa"
    second_root = module._state_paths()["transaction_root"] / second_txn
    second_restore = second_root / "legacy_restore"
    shutil.copytree(restore_root, second_restore)
    second_manifest = module._load_json(second_restore / "restore.manifest.json")
    second_manifest["txn_id"] = second_txn
    module._write_json_atomic(second_restore / "restore.manifest.json", second_manifest)
    second_manifest_sha = module._sha256(second_restore / "restore.manifest.json")
    second_journal = dict(journal)
    second_journal["txn_id"] = second_txn
    second_journal["from"] = {
        **journal["from"],
        "legacy_restore_path": str(second_restore),
        "legacy_restore_manifest_sha256": second_manifest_sha,
    }
    second_journal_path = second_root / "activation.v1.json"
    module._write_json_atomic(second_journal_path, second_journal)
    module._validate_journal(module._load_json(second_journal_path), second_journal_path)
    live_sha = module._sha256(world["pointer_path"])
    with pytest.raises(module.XinaoError) as failure:
        module._heal_restored_migrate_journal_if_needed(live_sha)
    assert failure.value.reason_code == "RECOVERY_CONFLICT"
    assert "multiple matching" in failure.value.detail
    assert module._load_json(journal_path)["state"] == "VERIFIED"
    assert module._load_json(second_journal_path)["state"] == "VERIFIED"
    with pytest.raises(module.XinaoError) as migrate_failure:
        module.bootstrap_migrate()
    assert migrate_failure.value.reason_code == "RECOVERY_CONFLICT"


def test_heal_preserves_foreign_release_extra_and_requires_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    txn_id = migrated["txn_id"]
    journal = module._load_json(module._journal_path(txn_id))
    restore_root = Path(journal["from"]["legacy_restore_path"])
    restore_manifest = module._verify_legacy_restore_bundle(
        restore_root,
        expected_manifest_sha256=journal["from"]["legacy_restore_manifest_sha256"],
        expected_tree_sha256=journal["from"]["legacy_restore_tree_sha256"],
    )
    # Partial world: skill + pointer restored; leave impurity in a captured release dir.
    module._apply_legacy_restore_bundle(journal, restore_root, restore_manifest)
    impure = (
        module._state_paths()["release_root"]
        / str(world["previous"]["release_id"])
        / "skill-bundle-noise"
    )
    impure.mkdir(parents=True, exist_ok=True)
    (impure / "x.txt").write_bytes(b"noise\n")
    assert module._load_json(module._journal_path(txn_id))["state"] == "VERIFIED"
    live_sha = module._sha256(world["pointer_path"])
    with pytest.raises(module.XinaoError) as failure:
        module._heal_restored_migrate_journal_if_needed(live_sha)
    assert failure.value.reason_code == "RECOVERY_REQUIRED"
    assert (impure / "x.txt").read_bytes() == b"noise\n"
    assert module._load_json(module._journal_path(txn_id))["state"] == "VERIFIED"


def test_failed_heal_blocks_new_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    txn_id = migrated["txn_id"]
    journal = module._load_json(module._journal_path(txn_id))
    restore_root = Path(journal["from"]["legacy_restore_path"])
    # Pointer restored to legacy, journal still VERIFIED, restore path retargeted foreign.
    module._write_bytes_atomic(world["pointer_path"], world["legacy_bytes"])
    foreign = tmp_path / "foreign_restore_bundle"
    import shutil

    shutil.copytree(journal["from"]["legacy_restore_path"], foreign)
    journal["from"] = {
        **journal["from"],
        "legacy_restore_path": str(foreign),
    }
    module._write_json_atomic(module._journal_path(txn_id), journal)
    before_journals = {
        path.name for path in module._state_paths()["transaction_root"].iterdir() if path.is_dir()
    }
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code in {
        "RECOVERY_REQUIRED",
        "RECOVERY_CONFLICT",
        "LEGACY_RESTORE_PATH_INVALID",
    }
    after_journals = {
        path.name for path in module._state_paths()["transaction_root"].iterdir() if path.is_dir()
    }
    assert after_journals == before_journals
    assert module._load_json(module._journal_path(txn_id))["state"] == "VERIFIED"
    with pytest.raises(module.XinaoError) as pending_failure:
        module._pending_journals()
    assert pending_failure.value.reason_code == "LEGACY_RESTORE_PATH_INVALID"


def test_canary_failure_migrate_rollback_trigger_differs_from_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)

    def fail_canary(journal):
        raise module.XinaoError("INJECTED_CANARY_FAILURE", "post-switch")

    monkeypatch.setattr(module, "_run_activation_canary", fail_canary)
    canary_receipt = module.bootstrap_migrate()
    assert canary_receipt["status"] == "ROLLED_BACK"
    assert canary_receipt["rollback_trigger"] == "CANARY_FAILURE"
    assert canary_receipt["reason_code"] == "INJECTED_CANARY_FAILURE"
    assert canary_receipt["completion_claim_allowed"] is False
    # Re-migrate successfully, then requested rollback uses a different trigger.
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    assert migrated["status"] == "MIGRATED"
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    requested = module.rollback_release()
    assert requested["rollback_trigger"] == "REQUESTED"
    assert requested["reason_code"] == "REQUESTED_ROLLBACK"
    assert requested["completion_claim_allowed"] is False


def test_ordinary_v2_to_v2_rollback_still_uses_previous_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-success migration path must not hijack ordinary previous_verified rollback."""

    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, _second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"v2-rollback-preserve"
    )
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(second["release_id"])]
    )
    module.activate_release(str(second["release_id"]))
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    receipt = module.rollback_release()
    pointer = module._load_json(module._state_paths()["pointer"])
    assert receipt["status"] == "ROLLED_BACK"
    assert receipt["operation"] == "ROLLBACK"
    assert "rollback_trigger" not in receipt
    assert pointer["generation"] == 3
    assert pointer["active"]["release_id"] == first["release_id"]
    assert pointer["previous_verified"]["release_id"] == second["release_id"]


def test_generic_worker_arguments_get_typed_rejection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    exit_code = module.main(["research", "--question", "q", "--CommonWorkKey", "wrong"])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["status"] == "PREFLIGHT_FAILED"
    assert result["reason_codes"] == ["INVOCATION_ARGUMENTS_INVALID"]
    assert result["user_operations_required"] == []


@pytest.mark.parametrize(
    "txn_id",
    (
        "..",
        "C:/absolute/activation",
        "xra_20260730T120000_../../escape",
    ),
)
def test_thin_rejects_malicious_transaction_ids_before_path_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, txn_id: str
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    pointer, _journal, _journal_path = _terminal_pointer(runtime, manifest, manifest_path)
    pointer["active"]["activation_txn_id"] = txn_id
    runtime._write_json_atomic(runtime._state_paths()["pointer"], pointer)
    bootstrap = _bootstrap_module()
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._runtime_entry_locked(["inspect"], tmp_path / "state")
    assert failure.value.reason_code == "ACTIVATION_TRANSACTION_ID_INVALID"


@pytest.mark.parametrize("mutation", ("extra_key", "unknown_state", "redirect_from"))
def test_thin_pending_journal_shape_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime = _module()
    first, first_path = _sealed_release(runtime, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(runtime, first, first_path)
    second, second_path = _sealed_release(
        runtime, tmp_path, monkeypatch, image_character="b", variant=b"pending"
    )
    with runtime._activation_lock():
        current = runtime._load_current_context()
        journal, journal_path = runtime._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
    if mutation == "extra_key":
        journal["unexpected"] = True
    elif mutation == "unknown_state":
        journal["state"] = "UNKNOWN"
    else:
        journal["from"]["active"]["release_manifest_path"] = str(
            tmp_path / "redirected-release.json"
        )
    runtime._write_json_atomic(journal_path, journal)
    bootstrap = _bootstrap_module()
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._pending_activation_journals(tmp_path / "state")
    expected = {
        "extra_key": "ACTIVATION_JOURNAL_SCHEMA_INVALID",
        "unknown_state": "ACTIVATION_STATE_INVALID",
        "redirect_from": "RELEASE_MANIFEST_PATH_INVALID",
    }
    assert failure.value.reason_code == expected[mutation]


@pytest.mark.parametrize("mutation", ("extra_key", "identity_drift", "skill_hash_drift"))
def test_thin_release_schema_and_identity_are_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    candidate = json.loads(json.dumps(manifest))
    if mutation == "extra_key":
        candidate["unexpected"] = True
    elif mutation == "identity_drift":
        candidate["release_identity_sha256"] = "0" * 64
    else:
        candidate["skill_hashes"]["skill_md_sha256"] = "0" * 64
    bootstrap = _bootstrap_module()
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._validate_release_manifest_shape(
            candidate,
            manifest_path=manifest_path,
            state_root=tmp_path / "state",
        )
        bootstrap._validate_release_skill_hashes(candidate, Path(candidate["skill_bundle_path"]))
    assert failure.value.reason_code in {
        "RELEASE_SCHEMA_INVALID",
        "RELEASE_IDENTITY_MISMATCH",
        "RELEASE_IMAGE_IDENTITY_INVALID",
        "RELEASE_SKILL_HASHES_MISMATCH",
    }


@pytest.mark.parametrize("mutation", ("case_collision", "extra_empty_dir", "too_many"))
def test_thin_bundle_inventory_rejects_case_empty_dir_and_count_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    active = runtime._release_ref_from_manifest(
        manifest,
        manifest_path,
        activation_txn_id="xra_20260730T120000_" + "1" * 16,
    )
    bundle_manifest_path = Path(manifest["skill_bundle_manifest_path"])
    bundle_manifest = runtime._load_json(bundle_manifest_path)
    if mutation == "case_collision":
        row = dict(bundle_manifest["files"][0])
        row["relative_path"] = str(row["relative_path"]).swapcase()
        bundle_manifest["files"].append(row)
        bundle_manifest["files"].sort(key=lambda value: value["relative_path"])
    elif mutation == "too_many":
        template = dict(bundle_manifest["files"][0])
        bundle_manifest["files"] = [
            {
                **template,
                "relative_path": f"bulk/{index:04d}.txt",
            }
            for index in range(4097)
        ]
    else:
        (Path(manifest["skill_bundle_path"]) / "empty-extra").mkdir()
    if mutation != "extra_empty_dir":
        bundle_manifest["tree_sha256"] = runtime._sha256_bytes(
            runtime._canonical_bytes(bundle_manifest["files"])
        )
        runtime._write_json_atomic(bundle_manifest_path, bundle_manifest)
        manifest["skill_bundle_manifest_sha256"] = runtime._sha256(bundle_manifest_path)
        manifest["skill_bundle_tree_sha256"] = bundle_manifest["tree_sha256"]
        active["skill_bundle_manifest_sha256"] = manifest["skill_bundle_manifest_sha256"]
        active["skill_bundle_tree_sha256"] = manifest["skill_bundle_tree_sha256"]
    bootstrap = _bootstrap_module()
    if mutation == "case_collision":
        monkeypatch.setattr(bootstrap.os.path, "normcase", lambda value: value)
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._validate_bundle(
            release_root=manifest_path.parent,
            manifest=manifest,
            active=active,
        )
    expected_codes = {
        "case_collision": "SKILL_BUNDLE_PATH_COLLISION",
        "extra_empty_dir": "SKILL_BUNDLE_FILE_SET_MISMATCH",
        "too_many": "SKILL_BUNDLE_INVENTORY_INVALID",
    }
    assert failure.value.reason_code == expected_codes[mutation]


def test_thin_child_executes_the_exact_verified_runtime_bytes() -> None:
    bootstrap = _bootstrap_module()
    payload = b"import sys\nsys.stdout.write('verified-runtime-bytes')\n"
    wrapper = bootstrap._runtime_wrapper(Path("sealed/runtime.py"), payload)
    completed = subprocess.run(
        [sys.executable, "-I", "-"],
        input=wrapper,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout == b"verified-runtime-bytes"
    assert completed.stderr == b""
    assert b"os.execv" not in wrapper


def test_thin_handoff_timeout_reaps_only_its_child_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _module()
    state_root = _state(runtime, tmp_path, monkeypatch)
    bootstrap = _bootstrap_module()
    monkeypatch.setattr(bootstrap, "RUNTIME_HANDOFF_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(bootstrap, "RUNTIME_REAP_TIMEOUT_SECONDS", 1.0)
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    started = time.monotonic()
    try:
        with pytest.raises(bootstrap.BootstrapError) as failure:
            with bootstrap._activation_lock(state_root):
                bootstrap._handoff_runtime_wrapper(process, b"x" * (8 * 1024 * 1024))
        assert failure.value.reason_code == "SKILL_RUNTIME_HANDOFF_FAILED"
        assert time.monotonic() - started < 5.0
        assert process.poll() is not None
        assert process.stdin is None
        assert not any(
            thread.name == "xinao-runtime-handoff" and thread.is_alive()
            for thread in threading.enumerate()
        )
        with bootstrap._activation_lock(state_root):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_thin_wrapper_preserves_non_ascii_runtime_and_state_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _module()
    unicode_root = tmp_path / "新澳状态根"
    manifest, manifest_path = _sealed_release(runtime, unicode_root, monkeypatch)
    _terminal_pointer(runtime, manifest, manifest_path)
    state_root = runtime._state_paths()["state_root"]
    bootstrap = _bootstrap_module()
    runtime_path, _runtime_payload, fence = bootstrap._runtime_entry_locked(["inspect"], state_root)
    assert "新澳状态根" in str(runtime_path)
    assert fence["state_root"] == str(state_root)
    encoded_fence = json.dumps(
        fence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    assert json.loads(encoded_fence.decode("ascii")) == fence
    probe = (
        "# -*- coding: utf-8 -*-\n"
        "import json, sys\n"
        "_value = json.dumps({'runtime_path': __file__, 'value': '新澳'}, ensure_ascii=False)\n"
        "sys.stdout.buffer.write((_value + '\\n').encode('utf-8'))\n"
    ).encode("utf-8")
    wrapper = bootstrap._runtime_wrapper(runtime_path, probe)
    wrapper.decode("ascii")
    completed = subprocess.run(
        [sys.executable, "-I", "-"],
        input=wrapper,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == b""
    observed = json.loads(completed.stdout.decode("utf-8"))
    assert observed == {"runtime_path": str(runtime_path), "value": "新澳"}


def test_dockerfile_stages_shadow_runtime_and_preserves_researcher_entrypoint() -> None:
    dockerfile = (ROOT / "docker" / "xinao-researcher" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY shadow-runtime/" in dockerfile
    assert "SHADOW_RUNTIME_TREE_SHA256" in dockerfile
    assert "io.xinao.researcher.shadow-runtime.sha256" in dockerfile
    assert 'ENTRYPOINT ["python", "-I", "/opt/xinao-researcher/entrypoint.py"]' in dockerfile
    assert "xinao.shadow_lifecycle" in dockerfile
    assert "xinao-shadow.pth" in dockerfile
    assert "PYTHONPATH=/opt/xinao-shadow" not in dockerfile


def test_build_stages_locked_shadow_runtime_into_docker_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for live COPY shadow-runtime/ not found: stage locked cone only."""
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock = module._load_shadow_runtime_lock(SKILL_ROOT)
    expected_rows = module._collect_shadow_runtime_rows(ROOT, lock)
    expected_tree = module._shadow_runtime_tree_sha256(expected_rows)
    expected_relatives = [relative for relative, _path, _content in expected_rows]
    observed: dict[str, object] = {}

    def on_before_build(values: list[str]) -> None:
        dockerfile = Path(values[values.index("--file") + 1])
        if dockerfile.name == "Dockerfile.tool-executor":
            return
        context = Path(values[-1])
        shadow_root = context / module.SHADOW_RUNTIME_CONTEXT_RELATIVE
        staged = sorted(
            path.relative_to(shadow_root).as_posix()
            for path in shadow_root.rglob("*")
            if path.is_file()
        )
        args = _parse_build_args(values)
        observed["context"] = str(context)
        observed["staged"] = staged
        observed["tree"] = args.get("SHADOW_RUNTIME_TREE_SHA256")
        # Context must remain the owned donor staging root, not source_root.
        assert context.resolve() != ROOT.resolve()
        assert str(ROOT.resolve()) not in str(context.resolve())
        assert staged == expected_relatives
        module._verify_staged_shadow_runtime(
            context,
            expected_rows,
            expected_tree_sha256=expected_tree,
        )

    _fake_build_environment(module, monkeypatch, dirty=False, on_before_build=on_before_build)
    receipt = module.build_release(ROOT, allow_dirty=False)
    assert receipt["status"] == "CANDIDATE_BUILT"
    assert observed["staged"] == expected_relatives
    assert observed["tree"] == expected_tree
    manifest = module._load_json(Path(receipt["release_manifest_path"]))
    assert manifest["source_identity"]["shadow_runtime_tree_sha256"] == expected_tree
    assert manifest["image_labels"]["io.xinao.researcher.shadow-runtime.sha256"] == expected_tree
    # Build context is cleaned after success.
    assert not Path(str(observed["context"])).exists()


def test_build_fails_closed_when_shadow_runtime_not_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Would have passed the weak path-string check before this regression was added."""
    module = _module()
    _state(module, tmp_path, monkeypatch)

    def skip_stage(build_context: Path, rows: list) -> Path:
        # Intentionally omit materialization while keeping destination absent.
        del rows
        return build_context / module.SHADOW_RUNTIME_CONTEXT_RELATIVE

    monkeypatch.setattr(module, "_stage_shadow_runtime", skip_stage)
    _fake_build_environment(module, monkeypatch, dirty=False)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "SHADOW_RUNTIME_STAGING_MISSING"


def test_shadow_runtime_stage_and_verify_are_hash_bound(tmp_path: Path) -> None:
    module = _module()
    lock = module._load_shadow_runtime_lock(SKILL_ROOT)
    rows = module._collect_shadow_runtime_rows(ROOT, lock)
    tree = module._shadow_runtime_tree_sha256(rows)
    build_context = tmp_path / "build-context"
    build_context.mkdir()
    staged = module._stage_shadow_runtime(build_context, rows)
    assert staged == build_context / "shadow-runtime"
    module._verify_staged_shadow_runtime(build_context, rows, expected_tree_sha256=tree)
    # Tamper one staged file: verification must fail closed.
    target = staged / "xinao" / "shadow_lifecycle" / "__main__.py"
    target.write_bytes(target.read_bytes() + b"#tamper\n")
    with pytest.raises(module.XinaoError) as failure:
        module._verify_staged_shadow_runtime(build_context, rows, expected_tree_sha256=tree)
    assert failure.value.reason_code in {
        "SHADOW_RUNTIME_STAGING_DRIFT",
        "SHADOW_RUNTIME_STAGING_HASH_MISMATCH",
    }


def test_shadow_command_construction_is_network_none_readonly_episode_only() -> None:
    module = _module()
    episode = Path("D:/tmp/episode-state")
    input_root = Path("D:/tmp/shadow-input")
    argv = module._build_shadow_docker_create_argv(
        docker="docker",
        image_id="sha256:" + "a" * 64,
        name="xinao-shadow-test",
        episode_root=episode,
        input_root=input_root,
        module_argv=["freeze", "--root", "/episode", "--request", "/input/request.json"],
    )
    joined = " ".join(argv)
    assert argv[:2] == ["docker", "create"]
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv
    assert "--cap-drop" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges:true" in joined
    assert "--entrypoint" in argv and argv[argv.index("--entrypoint") + 1] == "python"
    assert ("sha256:" + "a" * 64) in argv
    assert any(
        item.startswith("type=bind,source=") and "/episode" in item and "readonly" not in item
        for item in argv
    )
    assert any(
        item.startswith("type=bind,source=") and "/input" in item and item.endswith(",readonly")
        for item in argv
    )
    assert argv[-6:] == [
        "sha256:" + "a" * 64,
        "-I",
        "-m",
        "xinao.shadow_lifecycle",
        "freeze",
        "--root",
    ] or (
        "-m" in argv and argv[argv.index("-m") + 1] == "xinao.shadow_lifecycle" and "freeze" in argv
    )
    # No provider egress or auth mounts.
    assert "auth.json" not in joined
    assert "xinao_researcher_internal" not in joined
    assert "HTTP_PROXY" not in joined
    assert "PYTHONPATH" not in joined


def test_shadow_inspect_requires_source_and_live_image_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    registry = module._validate_registry()
    absent = module._shadow_live_status(registry, None, image_ok=False)
    assert absent["runtime_status"] == "RELEASE_ABSENT"
    manifest, _path = _sealed_release(module, tmp_path, monkeypatch, capability_version="1.2.2")
    _materialize_installed_from_release(module, tmp_path, monkeypatch, manifest)
    ready = module._shadow_live_status(registry, manifest, image_ok=True)
    assert ready["runtime_status"] == "AVAILABLE"
    assert ready["completion_claim_allowed"] is False
    broken = dict(manifest)
    broken_labels = dict(manifest["image_labels"])
    broken_labels.pop("io.xinao.researcher.shadow-runtime.sha256")
    broken["image_labels"] = broken_labels
    missing = module._shadow_live_status(registry, broken, image_ok=True)
    assert missing["runtime_status"] == "IMAGE_CAPABILITY_MISSING"
    drifted_root = tmp_path / "installed-skill-aligned"
    (drifted_root / "SKILL.md").write_bytes(b"drifted-skill-md\n")
    drifted = module._shadow_live_status(registry, manifest, image_ok=True)
    assert drifted["runtime_status"] == "PROJECTION_DRIFTED"


def test_shadow_parser_and_fresh_process_accept_verbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    parser = module._parser()
    args = parser.parse_args(
        [
            "shadow",
            "init",
            "--root",
            str(tmp_path / "ep"),
            "--seat-id",
            "s1",
            "--portfolio-ref",
            "p1",
        ]
    )
    assert args.command == "shadow"
    assert args.shadow_command == "init"
    for verb in ("inspect", "status", "freeze", "settle", "replay"):
        if verb in {"freeze", "settle"}:
            continue
        parsed = parser.parse_args(["shadow", verb, "--root", str(tmp_path / "ep")])
        assert parsed.shadow_command == verb

    portfolio_init = parser.parse_args(
        [
            "shadow",
            "portfolio-init",
            "--root",
            str(tmp_path / "pf"),
            "--seat-id",
            "s1",
            "--portfolio-ref",
            "p1",
        ]
    )
    assert portfolio_init.shadow_command == "portfolio-init"
    assert portfolio_init.seat_id == "s1"
    assert portfolio_init.portfolio_ref == "p1"
    portfolio_inspect = parser.parse_args(
        ["shadow", "portfolio-inspect", "--root", str(tmp_path / "pf")]
    )
    assert portfolio_inspect.shadow_command == "portfolio-inspect"
    portfolio_freeze = parser.parse_args(
        [
            "shadow",
            "portfolio-freeze",
            "--root",
            str(tmp_path / "pf"),
            "--request",
            str(tmp_path / "request.json"),
        ]
    )
    assert portfolio_freeze.shadow_command == "portfolio-freeze"
    portfolio_settle = parser.parse_args(
        [
            "shadow",
            "portfolio-settle",
            "--root",
            str(tmp_path / "pf"),
            "--outcome",
            str(tmp_path / "outcome.json"),
            "--settlement-ref",
            "settlement.1",
        ]
    )
    assert portfolio_settle.shadow_command == "portfolio-settle"
    assert portfolio_settle.settlement_ref == "settlement.1"
    portfolio_feedback = parser.parse_args(
        [
            "shadow",
            "portfolio-feedback",
            "--root",
            str(tmp_path / "pf"),
            "--kind",
            "NO_CHANGE_WITH_REASON",
            "--reason-code",
            "hold",
            "--notes",
            "carry",
        ]
    )
    assert portfolio_feedback.shadow_command == "portfolio-feedback"
    assert portfolio_feedback.kind == "NO_CHANGE_WITH_REASON"
    assert portfolio_feedback.reason_code == "hold"
    assert portfolio_feedback.notes == "carry"
    portfolio_replay = parser.parse_args(
        [
            "shadow",
            "portfolio-replay",
            "--root",
            str(tmp_path / "pf"),
            "--period-index",
            "1",
        ]
    )
    assert portfolio_replay.shadow_command == "portfolio-replay"
    assert portfolio_replay.period_index == 1
    assert set(module.SHADOW_SKILL_VERBS) == {
        "init",
        "inspect",
        "status",
        "freeze",
        "settle",
        "replay",
        "portfolio-init",
        "portfolio-inspect",
        "portfolio-freeze",
        "portfolio-settle",
        "portfolio-feedback",
        "portfolio-replay",
    }

    # Fresh process: parser-level reject without active pointer (bootstrap/runtime handoff path).
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SKILL_ROOT / "scripts" / "xinao.py"),
            "shadow",
            "inspect",
            "--root",
            str(tmp_path / "ep"),
        ],
        cwd=str(ROOT),
        env={**os.environ, "XINAO_SKILL_STATE_ROOT": str(tmp_path / "state")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    assert completed.returncode != 0
    payload = json.loads(completed.stdout.decode("utf-8", errors="replace"))
    assert payload.get("completion_claim_allowed") is False
    assert "reason_codes" in payload or payload.get("status") == "PREFLIGHT_FAILED"


def _shadow_inventory_module_names(inventory: list[str]) -> set[str]:
    """Map locked relative paths to importable module names."""
    modules: set[str] = set()
    for relative in inventory:
        posix = relative.replace("\\", "/")
        parts = posix.split("/")
        if not parts or not parts[-1].endswith(".py"):
            continue
        if parts[-1] == "__init__.py":
            modules.add(".".join(parts[:-1]))
        else:
            modules.add(".".join(parts[:-1] + [parts[-1][:-3]]))
    return modules


def _shadow_import_target_allowed(module_name: str, allowed: set[str]) -> bool:
    """True when an absolute xinao.* import resolves inside the locked inventory."""
    if module_name in allowed:
        return True
    # Package import is allowed when the package __init__ is inventoried.
    return module_name in allowed


def _collect_nested_non_inventory_xinao_imports(
    rows: list[tuple[str, Path, bytes]], allowed_modules: set[str]
) -> list[str]:
    """AST-scan inventory sources for absolute xinao imports outside the lock."""
    import ast

    violations: list[str] = []
    for relative, _path, content in rows:
        if not relative.endswith(".py"):
            continue
        tree = ast.parse(content.decode("utf-8"), filename=relative)
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                # Relative imports stay inside the staged package tree.
                if node.level and node.level > 0:
                    continue
                if node.module:
                    targets.append(node.module)
            for target in targets:
                if target != "xinao" and not target.startswith("xinao."):
                    continue
                if not _shadow_import_target_allowed(target, allowed_modules):
                    violations.append(f"{relative}:{getattr(node, 'lineno', '?')}:{target}")
    return violations


def test_shadow_runtime_inventory_is_import_closed() -> None:
    module = _module()
    lock = module._load_shadow_runtime_lock(SKILL_ROOT)
    rows = module._collect_shadow_runtime_rows(ROOT, lock)
    assert any(rel.endswith("shadow_lifecycle/__main__.py") for rel, _p, _b in rows)
    assert not any("postgres" in rel for rel, _p, _b in rows)
    assert not any("catalog" in rel for rel, _p, _b in rows)
    assert not any("special_number_evidence" in rel for rel, _p, _b in rows)
    tree = module._shadow_runtime_tree_sha256(rows)
    assert re.fullmatch(r"[0-9a-f]{64}", tree)

    allowed = _shadow_inventory_module_names([rel for rel, _p, _b in rows])
    violations = _collect_nested_non_inventory_xinao_imports(rows, allowed)
    assert violations == [], (
        "shadow-runtime inventory must not import xinao modules outside the "
        f"locked cone (lazy imports included): {violations}"
    )


def test_shadow_runtime_staged_cone_init_reaches_write_manifest(tmp_path: Path) -> None:
    """Staged inventory alone must support init -> write_manifest without catalog."""
    module = _module()
    lock = module._load_shadow_runtime_lock(SKILL_ROOT)
    rows = module._collect_shadow_runtime_rows(ROOT, lock)
    tree = module._shadow_runtime_tree_sha256(rows)
    build_context = tmp_path / "build-context"
    build_context.mkdir()
    staged = module._stage_shadow_runtime(build_context, rows)
    module._verify_staged_shadow_runtime(build_context, rows, expected_tree_sha256=tree)

    # Fresh interpreter path: only staged cone on sys.path (no full xinao_discovery/src).
    episode = tmp_path / "episode"
    episode.mkdir()
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(staged)!r})\n"
        "from xinao.shadow_lifecycle.consumer import init_episode\n"
        "from xinao.shadow_lifecycle.store import MANIFEST_NAME, detect_phase, EpisodePhase\n"
        f"episode = Path({str(episode)!r})\n"
        "receipt = init_episode(\n"
        "    root=episode,\n"
        "    seat_id='seat.cone.smoke',\n"
        "    portfolio_ref='portfolio.cone.smoke',\n"
        ")\n"
        "assert receipt['ok'] is True\n"
        "assert receipt['phase'] == EpisodePhase.INIT.value\n"
        "manifest_path = episode / MANIFEST_NAME\n"
        "assert manifest_path.is_file(), 'write_manifest must materialize package_manifest'\n"
        "manifest = json.loads(manifest_path.read_text(encoding='utf-8'))\n"
        "assert manifest.get('schema_version') == "
        "'xinao.shadow_lifecycle.package_manifest.v1'\n"
        "assert 'content_hash' in manifest and manifest['files']\n"
        "assert detect_phase(episode) == EpisodePhase.INIT\n"
        "print(json.dumps({'ok': True, 'phase': receipt['phase'], "
        "'manifest_files': sorted(manifest['files'])}))\n"
    )
    # Ensure third-party pins used by the cone are importable from the test env.
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
        cwd=str(tmp_path),
    )
    assert completed.returncode == 0, (
        "staged-cone init/write_manifest smoke failed:\n"
        f"stdout={completed.stdout.decode('utf-8', errors='replace')}\n"
        f"stderr={completed.stderr.decode('utf-8', errors='replace')}"
    )
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["phase"] == "INIT"
    assert "seat.v1.json" in payload["manifest_files"]
    assert "consumer_receipt.v1.json" in payload["manifest_files"]


def _prepare_migrated_world_with_later_active(
    module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    migrated = module.bootstrap_migrate()
    later, later_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="e",
        variant=b"sync-projection-later\n",
    )
    _install_bootstrap_fence(
        module,
        monkeypatch,
        ["activate", "--release-id", str(later["release_id"])],
    )
    activated = module.activate_release(str(later["release_id"]))
    assert activated["status"] == "VERIFIED"
    world["migrated"] = migrated
    world["later"] = later
    world["later_path"] = later_path
    world["installed_after_migrate"] = _installed_tree_map(Path(world["installed"]))
    return world


def test_sync_projection_mid_failure_auto_restores_previous_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_migrated_world_with_later_active(module, tmp_path, monkeypatch)
    previous = dict(world["installed_after_migrate"])
    pointer_before = module._state_paths()["pointer"].read_bytes()

    def crash_after_first_live_replace(phase: str, relative: str) -> None:
        # SKILL.md often matches across sealed releases; crash on the first live replace
        # that actually mutates (variant file / other drifted ordinary path).
        if phase == "forward:after-replace":
            raise module.XinaoError("INJECTED_SYNC_CRASH", relative)

    monkeypatch.setattr(module, "_projection_fault_point", crash_after_first_live_replace)
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    rolled = module.sync_projection()
    assert rolled["status"] == "ROLLED_BACK"
    assert rolled["failure_reason"]["reason_code"] == "INJECTED_SYNC_CRASH"
    assert module._state_paths()["pointer"].read_bytes() == pointer_before
    assert _installed_tree_map(Path(world["installed"])) == previous
    monkeypatch.setattr(module, "_projection_fault_point", lambda _phase, _relative: None)
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    synced = module.sync_projection()
    assert synced["status"] == "SYNCED"
    assert _installed_tree_map(Path(world["installed"])) == _active_skill_bundle_map(
        module, world["later"]
    )


def test_sync_projection_recover_continues_prepared_after_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_migrated_world_with_later_active(module, tmp_path, monkeypatch)
    previous = dict(world["installed_after_migrate"])

    def crash_before_first_live_replace(phase: str, relative: str) -> None:
        if phase == "forward:before-replace":
            raise module.XinaoError("INJECTED_SYNC_STAGE_CRASH", relative)

    monkeypatch.setattr(module, "_projection_fault_point", crash_before_first_live_replace)
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    rolled = module.sync_projection()
    # Crash before replace is caught and auto-restored to previous installed tree.
    assert rolled["status"] == "ROLLED_BACK"
    assert rolled["failure_reason"]["reason_code"] == "INJECTED_SYNC_STAGE_CRASH"
    assert _installed_tree_map(Path(world["installed"])) == previous
    # Explicit PREPARED journal: seal, then kill before forward project so recover can continue.
    monkeypatch.setattr(module, "_projection_fault_point", lambda _phase, _relative: None)
    original_continue = module._continue_sync_projection_journal
    calls = {"n": 0}

    def continue_once(journal: dict[str, object], journal_path: Path):
        calls["n"] += 1
        if calls["n"] == 1:
            module._materialize_sync_projection_contract(journal)
            raise module.XinaoError("INJECTED_AFTER_SEAL", str(journal["txn_id"]))
        return original_continue(journal, journal_path)

    monkeypatch.setattr(module, "_continue_sync_projection_journal", continue_once)
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    with pytest.raises(module.XinaoError) as failure:
        module.sync_projection()
    assert failure.value.reason_code == "INJECTED_AFTER_SEAL"
    pending = module._pending_journals()
    assert len(pending) == 1
    assert pending[0][0]["operation"] == "SYNC_PROJECTION"
    assert pending[0][0]["state"] == "PREPARED"
    monkeypatch.setattr(module, "_continue_sync_projection_journal", original_continue)
    _install_bootstrap_fence(module, monkeypatch, ["recover"])
    recovered = module.recover_release(pending[0][0]["txn_id"])
    assert recovered["status"] == "SYNCED"
    assert _installed_tree_map(Path(world["installed"])) == _active_skill_bundle_map(
        module, world["later"]
    )


def test_sync_projection_rejects_foreign_entry_and_keeps_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_migrated_world_with_later_active(module, tmp_path, monkeypatch)
    previous = dict(world["installed_after_migrate"])
    installed = Path(world["installed"])
    pointer_before = module._state_paths()["pointer"].read_bytes()

    original_materialize = module._materialize_sync_projection_contract

    def inject_foreign_after_seal(journal: dict[str, object]) -> dict[str, object]:
        receipt = original_materialize(journal)
        (installed / "foreign-unclassified.txt").write_bytes(b"foreign-bytes\n")
        return receipt

    monkeypatch.setattr(module, "_materialize_sync_projection_contract", inject_foreign_after_seal)
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    with pytest.raises(module.XinaoError) as failure:
        module.sync_projection()
    # Foreign entries are fail-closed: forward refuses them, and restore refuses to claim
    # success while unclassified bytes remain outside previous∪target.
    assert failure.value.reason_code in {
        "INSTALL_PROJECTION_FOREIGN_ENTRY",
        "RECOVERY_CONFLICT",
    }
    assert module._state_paths()["pointer"].read_bytes() == pointer_before
    restored = _installed_tree_map(installed)
    for relative, payload in previous.items():
        assert restored.get(relative) == payload


def test_sync_projection_fresh_installed_parser_and_inspect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_migrated_world_with_later_active(module, tmp_path, monkeypatch)
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    synced = module.sync_projection()
    assert synced["status"] == "SYNCED"
    # Fresh installed entry must parse sync-projection and report ALIGNED projection.
    completed = _run_installed_xinao(module, world, "sync-projection")
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    again = _json_stdout(completed)
    assert again["status"] == "ALREADY_ALIGNED"
    inspect_proc = _run_installed_xinao(module, world, "inspect")
    # inspect may fail closed on egress/auth; still must surface projection status honestly.
    payload = _json_stdout(inspect_proc)
    projection = payload.get("installed_projection") or {}
    assert projection.get("status") == "ALIGNED"
    assert projection.get("completion_claim_allowed") is False
    assert payload.get("shadow", {}).get("completion_claim_allowed") is False
    # Parser accepts the verb.
    parser = module._parser()
    args = parser.parse_args(["sync-projection"])
    assert args.command == "sync-projection"


def _prepare_synced_projection_world(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    launcher_payload: bytes | None = None,
) -> dict[str, object]:
    active, active_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="1",
        package_version="1.3.1",
        capability_version="1.2.1",
        launcher_payload=launcher_payload,
    )
    pointer, journal, journal_path = _terminal_pointer(
        module,
        active,
        active_path,
        generation=3,
        txn_suffix="3" * 16,
    )
    import shutil

    installed = tmp_path / "installed_skill"
    shutil.copytree(Path(str(active["skill_bundle_path"])), installed)
    (installed / "SKILL.md").write_bytes(
        (installed / "SKILL.md").read_bytes() + b"\n# force-real-sync\n"
    )
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(module, "DEFAULT_INSTALLED_SKILL_ROOT", installed)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda value: _canary_value(module, value),
    )
    _install_bootstrap_fence(module, monkeypatch, ["sync-projection"])
    synced = module.sync_projection()
    assert synced["status"] == "SYNCED"
    assert _installed_tree_map(installed) == _active_skill_bundle_map(module, active)
    return {
        "active": active,
        "active_path": active_path,
        "pointer": pointer,
        "journal": journal,
        "journal_path": journal_path,
        "installed": installed,
        "sync": synced,
    }


def _lineage_canary(module, journal: dict[str, object]) -> dict[str, object]:
    module._verify_stable_installed_launcher(journal)
    return _canary_value(module, journal)


def test_activate_selects_real_installed_projection_after_old_sync_and_forward_upgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    old_launcher = b"from __future__ import annotations\n# sealed-old-launcher\n"
    world = _prepare_synced_projection_world(
        module,
        tmp_path,
        monkeypatch,
        launcher_payload=old_launcher,
    )
    old_sync = module._find_latest_verified_sync_projection()
    assert old_sync is not None
    assert old_sync[1]["stable_launcher_sha256"] == module._sha256_bytes(old_launcher)

    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda value: _lineage_canary(module, value),
    )
    for index, image_character in enumerate(("4", "5"), start=1):
        target, target_path = _sealed_release(
            module,
            tmp_path,
            monkeypatch,
            image_character=image_character,
            package_version=f"1.3.{index + 1}",
            capability_version=f"1.2.{index + 1}",
        )
        monkeypatch.setattr(
            module,
            "_prepare_forward_upgrade_target",
            lambda target=target, target_path=target_path: (target, target_path),
        )
        upgraded = module.bootstrap_forward_upgrade()
        assert upgraded["status"] == "UPGRADED"
        world[f"forward_{index}"] = upgraded
        world[f"forward_release_{index}"] = target

    latest_forward = module._find_verified_forward_upgrade_projection()
    installed_launcher = Path(world["installed"]) / "scripts" / "xinao.py"
    assert latest_forward[1]["stable_launcher_sha256"] == module._sha256(installed_launcher)
    assert old_sync[1]["stable_launcher_sha256"] != module._sha256(installed_launcher)

    candidate, candidate_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="6",
        package_version="1.3.9",
        capability_version="1.2.9",
        variant=b"ordinary-activate-after-forward-lineage\n",
    )
    _install_bootstrap_fence(
        module,
        monkeypatch,
        ["activate", "--release-id", str(candidate["release_id"])],
    )
    activated = module.activate_release(str(candidate["release_id"]))
    assert activated["status"] == "VERIFIED"
    assert activated["release_id"] == candidate["release_id"]
    activation_journal = module._load_json(module._journal_path(activated["txn_id"]))
    assert activation_journal["state"] == "VERIFIED"

    # A matching exact-from witness that becomes VERIFIED only after this ACTIVATE's
    # prepared boundary must not retroactively enter its lineage.  The prior matching
    # forward projection remains a valid fallback for the same installed bytes.
    future_path = module._journal_path(str(world["forward_2"]["txn_id"]))
    future = module._load_json(future_path)
    future["updated_at"] = "2999-01-01T00:00:00Z"
    module._write_json_atomic(future_path, future)
    selected, _receipt = module._find_installed_projection_witness(activation_journal)
    assert selected["txn_id"] == world["forward_1"]["txn_id"]


def _prepare_rolled_back_activation_conflict(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    world = _prepare_synced_projection_world(module, tmp_path, monkeypatch)
    candidate, candidate_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="7",
        package_version="1.3.7",
        capability_version="1.2.7",
        variant=b"conflict-target\n",
    )

    def fail_launcher(_journal: dict[str, object]) -> dict[str, object]:
        raise module.XinaoError(
            "INSTALLED_LAUNCHER_IDENTITY_MISMATCH",
            str(Path(world["installed"]) / "scripts" / "xinao.py"),
        )

    monkeypatch.setattr(module, "_run_activation_canary", fail_launcher)
    _install_bootstrap_fence(
        module,
        monkeypatch,
        ["activate", "--release-id", str(candidate["release_id"])],
    )
    with pytest.raises(module.XinaoError) as failure:
        module.activate_release(str(candidate["release_id"]))
    assert failure.value.reason_code == "RECOVERY_CONFLICT"
    pointer = module._load_json(module._state_paths()["pointer"])
    txn_id = str(pointer["active"]["activation_txn_id"])
    conflict = module._load_json(module._journal_path(txn_id))
    assert conflict["state"] == "RECOVERY_CONFLICT"
    assert conflict["operation"] == "ACTIVATE"
    assert conflict["failure_reason"]["reason_code"] == "INSTALLED_LAUNCHER_IDENTITY_MISMATCH"
    world.update(
        {
            "candidate": candidate,
            "candidate_path": candidate_path,
            "conflict": conflict,
            "txn_id": txn_id,
        }
    )
    return world


def test_explicit_conflict_recovery_seals_exact_rolled_back_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_rolled_back_activation_conflict(module, tmp_path, monkeypatch)
    txn_id = str(world["txn_id"])
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda value: _lineage_canary(module, value),
    )

    bootstrap = _bootstrap_module()
    state_root = module._state_paths()["state_root"]
    assert bootstrap._pointer_requires_migration_entry(state_root, ["recover", "--txn-id", txn_id])
    assert not bootstrap._pointer_requires_migration_entry(state_root, ["recover"])
    routed: list[list[str]] = []
    monkeypatch.setattr(
        bootstrap,
        "_run_companion_runtime",
        lambda argv: routed.append(list(argv)) or 0,
    )
    assert bootstrap._run_runtime(["recover", "--txn-id", txn_id]) == 0
    assert routed == [["recover", "--txn-id", txn_id]]

    recovered = module.recover_release(txn_id)
    assert recovered["status"] == "ROLLED_BACK"
    assert recovered["recovered_from"] == "RECOVERY_CONFLICT"
    sealed = module._load_json(module._journal_path(txn_id))
    pointer_sha256 = module._sha256(module._state_paths()["pointer"])
    assert sealed["state"] == "ROLLED_BACK"
    assert sealed["terminal_pointer_sha256"] == pointer_sha256
    assert sealed["switched_pointer_sha256"] == pointer_sha256


@pytest.mark.parametrize(
    "mutation", ("pointer_generation", "installed_tree", "different_conflict_reason")
)
def test_explicit_conflict_recovery_rejects_unbound_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    module = _module()
    world = _prepare_rolled_back_activation_conflict(module, tmp_path, monkeypatch)
    txn_id = str(world["txn_id"])
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda value: _lineage_canary(module, value),
    )
    if mutation == "pointer_generation":
        pointer_path = module._state_paths()["pointer"]
        pointer = module._load_json(pointer_path)
        pointer["generation"] += 1
        module._write_json_atomic(pointer_path, pointer)
    elif mutation == "installed_tree":
        skill_md = Path(world["installed"]) / "SKILL.md"
        skill_md.write_bytes(skill_md.read_bytes() + b"\n# tampered-after-conflict\n")
    else:
        journal_path = module._journal_path(txn_id)
        conflict = module._load_json(journal_path)
        conflict["failure_reason"] = {
            "reason_code": "UNRELATED_RECOVERY_FAILURE",
            "detail": "must not enter the selector-specific recovery cone",
        }
        module._write_json_atomic(journal_path, conflict)

    with pytest.raises(module.XinaoError) as failure:
        module.recover_release(txn_id)
    assert failure.value.reason_code in {
        "RECOVERY_CONFLICT",
        "INSTALL_PROJECTION_TARGET_INCOMPLETE",
    }
    assert module._load_json(module._journal_path(txn_id))["state"] == "RECOVERY_CONFLICT"


# ---------------------------------------------------------------------------
# Protocol-v2 forward upgrade: installed 1.2.0 pre-shadow → 1.3.0 target
# ---------------------------------------------------------------------------


def _pre_shadow_skill_hashes(module, root: Path) -> dict[str, str]:
    paths = {
        "skill_md_sha256": root / "SKILL.md",
        "skill_invoker_sha256": root / "scripts" / "xinao.py",
        "capability_registry_sha256": root / "references" / "capabilities.v1.json",
        "charter_sha256": root / "references" / "researcher-charter.v1.json",
        "output_schema_sha256": root / "references" / "researcher-output.v2.schema.json",
        "material_bundle_schema_sha256": root / "references" / "material-bundle.v1.schema.json",
        "runtime_lock_sha256": root / "references" / "researcher-runtime-lock.v1.json",
        "meta_sha256": root / "references" / "meta.md",
    }
    assert set(paths) == set(module.PRE_SHADOW_SKILL_HASH_KEYS)
    return {key: module._sha256(path) for key, path in paths.items()}


def _sealed_pre_shadow_v2_release(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_character: str = "a",
    package_version: str = "1.2.0",
    capability_version: str = "1.1.0",
    variant: bytes | None = None,
) -> tuple[dict[str, object], Path]:
    """Seal a historical protocol-v2 release without shadow-runtime identity fields."""

    state = _state(module, tmp_path, monkeypatch)
    # Historical pre-shadow skill tree: omit shadow-runtime lock (not part of 1.2.0 seal).
    source_rows = module._source_bundle_files(SKILL_ROOT)
    if variant is not None:
        source_rows.append(
            (
                "references/test-release-variant.txt",
                tmp_path / "unused-source-path",
                variant,
            )
        )
        source_rows.sort(key=lambda item: item[0])
    source_rows = [row for row in source_rows if row[0] != "references/shadow-runtime-lock.v1.json"]
    bundle_manifest = module._skill_bundle_manifest(source_rows, package_version=package_version)
    temp_bundle = tmp_path / f"pre-shadow-bundle-{image_character}"
    if temp_bundle.exists():
        import shutil

        shutil.rmtree(temp_bundle)
    module._materialize_skill_bundle(temp_bundle, source_rows, bundle_manifest)
    hashes = _pre_shadow_skill_hashes(module, temp_bundle)
    source_identity = {
        "source_commit": "c" * 40,
        "source_tree": "d" * 40,
        "source_dirty": False,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "grok_donor_binary_sha256": "a" * 64,
    }
    source_identity_sha256 = module._sha256_bytes(module._canonical_bytes(source_identity))
    image_id = "sha256:" + image_character * 64
    labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        "io.xinao.researcher.grok-donor-binary.sha256": source_identity["grok_donor_binary_sha256"],
        "io.xinao.researcher.charter.sha256": hashes["charter_sha256"],
        "io.xinao.researcher.output-schema.sha256": hashes["output_schema_sha256"],
        "io.xinao.researcher.material-bundle-schema.sha256": hashes[
            "material_bundle_schema_sha256"
        ],
        "io.xinao.researcher.runtime-lock.sha256": hashes["runtime_lock_sha256"],
        "io.xinao.researcher.skill-invoker.sha256": hashes["skill_invoker_sha256"],
        "io.xinao.researcher.dockerfile.sha256": "1" * 64,
        "io.xinao.researcher.entrypoint.sha256": "2" * 64,
        "io.xinao.researcher.source-identity.sha256": source_identity_sha256,
        "io.xinao.researcher.requested-model": "grok-4.5",
    }
    manifest: dict[str, object] = {
        "schema_version": module.RELEASE_SCHEMA,
        "release_id": "pending",
        "package_version": package_version,
        "capability_id": "researcher-container",
        "capability_version": capability_version,
        "charter_version": capability_version,
        "runtime_version": capability_version,
        "release_identity_sha256": "pending",
        "source_identity": source_identity,
        "skill_bundle_path": "pending",
        "skill_bundle_manifest_path": "pending",
        "skill_bundle_manifest_sha256": "pending",
        "skill_bundle_tree_sha256": bundle_manifest["tree_sha256"],
        "image_tag_observational": "xinao-researcher:pre-shadow-test",
        "image_id": image_id,
        "image_entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
        "image_labels": labels,
        "skill_hashes": hashes,
        "required_bootstrap_protocol": 2,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    identity_sha256 = module._sha256_bytes(
        module._canonical_bytes(
            module._release_identity_payload(manifest, include_shadow_runtime=False)
        )
    )
    release_id = f"researcher-{capability_version}-{identity_sha256[:16]}"
    release_root = state / "researcher_container" / "releases" / release_id
    manifest_path = release_root / "release.json"
    manifest.update(
        {
            "release_id": release_id,
            "release_identity_sha256": identity_sha256,
            "skill_bundle_path": str(release_root / "skill-bundle"),
            "skill_bundle_manifest_path": str(release_root / "skill-bundle.manifest.json"),
            "skill_bundle_manifest_sha256": module._sha256_bytes(
                module._canonical_bytes(bundle_manifest)
            ),
        }
    )
    module._materialize_skill_bundle(release_root / "skill-bundle", source_rows, bundle_manifest)
    module._write_json_atomic(
        release_root / "skill-bundle.manifest.json", bundle_manifest, create_new=True
    )
    module._write_json_atomic(manifest_path, manifest, create_new=True)
    module._validate_sealed_protocol_v2_release(manifest, manifest_path)
    with pytest.raises(module.XinaoError) as exact_failure:
        module._validate_release_manifest(manifest, manifest_path)
    assert exact_failure.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }
    return manifest, manifest_path


def _prepare_v2_forward_upgrade_world(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    previous, previous_path = _sealed_pre_shadow_v2_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        package_version="1.2.0",
        capability_version="1.1.0",
        variant=b"previous-pre-shadow\n",
    )
    active, active_path = _sealed_pre_shadow_v2_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="b",
        package_version="1.2.0",
        capability_version="1.1.0",
        variant=b"active-pre-shadow-1.2.0\n",
    )
    previous_ref = module._release_ref_from_manifest(
        previous, previous_path, activation_txn_id="xra_20260729T120000_" + "c" * 16
    )
    # Terminal journal for previous is not required for forward-upgrade seal; active has one.
    pointer, journal, journal_path = _terminal_pointer(
        module,
        active,
        active_path,
        generation=2,
        txn_suffix="a" * 16,
        previous_verified=previous_ref,
    )
    # Install a drifted skill tree from the active historical skill-bundle.
    import shutil

    active_bundle = Path(str(active["skill_bundle_path"]))
    installed = tmp_path / "installed_skill"
    if installed.exists():
        shutil.rmtree(installed)
    shutil.copytree(active_bundle, installed)
    (installed / "SKILL.md").write_bytes(
        (installed / "SKILL.md").read_bytes() + b"\n# installed-pre-shadow-drift\n"
    )
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(module, "DEFAULT_INSTALLED_SKILL_ROOT", installed)

    # Target must match current source skill-bundle identity so post-upgrade
    # idempotent re-entry can return ALREADY_* (schema + tree + versions).
    target, target_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="c",
        package_version="1.3.21",
        capability_version="1.2.15",
    )
    monkeypatch.setattr(
        module,
        "_prepare_forward_upgrade_target",
        lambda: (target, target_path),
    )
    pointer_path = module._state_paths()["pointer"]
    return {
        "active": active,
        "active_path": active_path,
        "previous": previous,
        "previous_path": previous_path,
        "pointer": pointer,
        "pointer_path": pointer_path,
        "pointer_bytes": pointer_path.read_bytes(),
        "active_manifest_bytes": active_path.read_bytes(),
        "previous_manifest_bytes": previous_path.read_bytes(),
        "journal": journal,
        "journal_path": journal_path,
        "installed": installed,
        "installed_snapshot": {
            relative.as_posix(): (installed / relative).read_bytes()
            for relative in [
                path.relative_to(installed) for path in installed.rglob("*") if path.is_file()
            ]
        },
        "target": target,
        "target_path": target_path,
    }


def test_ordinary_exact_validation_fails_closed_on_pre_shadow_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v2_forward_upgrade_world(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as failure:
        module._load_current_context(require_terminal=True)
    assert failure.value.reason_code in {
        "RELEASE_SOURCE_IDENTITY_INVALID",
        "RELEASE_SCHEMA_INVALID",
    }
    with pytest.raises(module.XinaoError) as migrate_failure:
        module.bootstrap_migrate()
    assert migrate_failure.value.reason_code == "FORWARD_UPGRADE_REQUIRED"
    # Historical manifests must remain byte-identical.
    assert Path(world["active_path"]).read_bytes() == world["active_manifest_bytes"]
    assert Path(world["previous_path"]).read_bytes() == world["previous_manifest_bytes"]


def test_bootstrap_forward_upgrade_1_2_0_v2_to_1_3_0_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v2_forward_upgrade_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    receipt = module.bootstrap_forward_upgrade()
    assert receipt["status"] == "UPGRADED"
    assert receipt["operation"] == "FORWARD_UPGRADE"
    assert receipt["release_id"] == world["target"]["release_id"]
    assert receipt["completion_claim_allowed"] is False
    # Pointer advanced; previous_verified cleared (independent restore is the rollback witness).
    pointer = module._load_json(module._state_paths()["pointer"])
    assert pointer["schema_version"] == module.CURRENT_POINTER_SCHEMA
    assert pointer["generation"] == 3
    assert pointer["active"]["release_id"] == world["target"]["release_id"]
    assert pointer["previous_verified"] is None
    # Historical release bytes never rewritten / relabeled.
    assert Path(world["active_path"]).read_bytes() == world["active_manifest_bytes"]
    assert Path(world["previous_path"]).read_bytes() == world["previous_manifest_bytes"]
    # Target is exact current schema.
    target_manifest = module._load_json(Path(world["target_path"]))
    module._validate_release_manifest(target_manifest, Path(world["target_path"]))
    assert "shadow_runtime_tree_sha256" in target_manifest["source_identity"]
    # Installed projection matches target skill-bundle.
    alignment = module._installed_projection_alignment(target_manifest)
    assert alignment["status"] == "ALIGNED"
    # Idempotent re-entry.
    again = module.bootstrap_forward_upgrade()
    assert again["status"] in {"ALREADY_UPGRADED", "ALREADY_CURRENT"}
    assert again["release_id"] == world["target"]["release_id"]


def test_bootstrap_forward_upgrade_requested_rollback_restores_exact_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v2_forward_upgrade_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    upgraded = module.bootstrap_forward_upgrade()
    assert upgraded["status"] == "UPGRADED"
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    rolled = module.rollback_release()
    assert rolled["status"] == "ROLLED_BACK"
    assert rolled["operation"] == "FORWARD_UPGRADE"
    assert module._state_paths()["pointer"].read_bytes() == world["pointer_bytes"]
    assert Path(world["active_path"]).read_bytes() == world["active_manifest_bytes"]
    restored = _installed_tree_map(Path(world["installed"]))
    for relative, payload in world["installed_snapshot"].items():
        assert restored.get(relative) == payload


def test_bootstrap_forward_upgrade_tamper_rejects_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v2_forward_upgrade_world(module, tmp_path, monkeypatch)
    # Tamper active historical release.json after world prep.
    active_path = Path(world["active_path"])
    payload = json.loads(active_path.read_text(encoding="utf-8"))
    payload["image_tag_observational"] = "tampered"
    active_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    pointer_before = world["pointer_bytes"]
    installed_before = dict(world["installed_snapshot"])
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_forward_upgrade()
    assert failure.value.reason_code in {
        "RELEASE_MANIFEST_IDENTITY_MISMATCH",
        "RELEASE_POINTER_IDENTITY_MISMATCH",
        "RELEASE_IDENTITY_MISMATCH",
        "RELEASE_IMAGE_IDENTITY_INVALID",
    }
    assert module._state_paths()["pointer"].read_bytes() == pointer_before
    restored = _installed_tree_map(Path(world["installed"]))
    for relative, payload in installed_before.items():
        assert restored.get(relative) == payload


def test_bootstrap_forward_upgrade_crash_after_pointer_switch_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v2_forward_upgrade_world(module, tmp_path, monkeypatch)
    original_post = module._project_migration_post_pointer
    calls = {"n": 0}

    def crash_once(journal: dict[str, object]) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise module.XinaoError("INJECTED_CRASH", "after pointer switch")
        return original_post(journal)

    monkeypatch.setattr(module, "_project_migration_post_pointer", crash_once)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    rolled = module.bootstrap_forward_upgrade()
    assert rolled["status"] == "ROLLED_BACK"
    assert rolled["operation"] == "FORWARD_UPGRADE"
    assert module._state_paths()["pointer"].read_bytes() == world["pointer_bytes"]
    # Re-run after crash recovery restores source world.
    monkeypatch.setattr(module, "_project_migration_post_pointer", original_post)
    receipt = module.bootstrap_forward_upgrade()
    assert receipt["status"] == "UPGRADED"
    pointer = module._load_json(module._state_paths()["pointer"])
    assert pointer["active"]["release_id"] == world["target"]["release_id"]


def test_bootstrap_forward_upgrade_crash_midway_then_recover_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v2_forward_upgrade_world(module, tmp_path, monkeypatch)
    original_post = module._project_migration_post_pointer

    def crash_before_finish(journal: dict[str, object]) -> None:
        original_post(journal)
        raise module.XinaoError("INJECTED_CRASH", "after projection before canary")

    monkeypatch.setattr(module, "_project_migration_post_pointer", crash_before_finish)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    first = module.bootstrap_forward_upgrade()
    assert first["status"] == "ROLLED_BACK"
    # Leave a prepared pending journal by re-entering prepare only, then recover.
    monkeypatch.setattr(module, "_project_migration_post_pointer", original_post)

    prepared_holder: dict[str, object] = {}

    original_continue = module._continue_forward_upgrade_journal

    def capture_and_stop(journal: dict[str, object], journal_path: Path) -> dict[str, object]:
        prepared_holder["journal"] = journal
        prepared_holder["path"] = journal_path
        # Simulate crash immediately after PREPARED journal is sealed, before continue.
        raise module.XinaoError("INJECTED_CRASH", "after prepared")

    # Force a fresh upgrade attempt that stops after journal create by intercepting continue
    # only once after capture path rebuilds prepared state.
    original_single = module._bootstrap_forward_upgrade_singleflight

    def single_with_inject() -> dict[str, object]:
        # First call path: use real implementation but inject crash after PREPARED write.
        original_write = module._write_json_atomic
        written = {"journal": False}

        def write_hook(path: Path, value: object, create_new: bool = False) -> None:
            original_write(path, value, create_new=create_new)
            if (
                isinstance(value, dict)
                and value.get("operation") == "FORWARD_UPGRADE"
                and value.get("state") == "PREPARED"
                and path.name == "activation.v1.json"
            ):
                written["journal"] = True
                raise module.XinaoError("INJECTED_CRASH", "after prepared journal")

        monkeypatch.setattr(module, "_write_json_atomic", write_hook)
        try:
            return original_single()
        finally:
            monkeypatch.setattr(module, "_write_json_atomic", original_write)

    with pytest.raises(module.XinaoError) as injected:
        single_with_inject()
    assert injected.value.reason_code == "INJECTED_CRASH"
    pending = module._pending_journals()
    assert len(pending) == 1
    assert pending[0][0]["operation"] == "FORWARD_UPGRADE"
    assert pending[0][0]["state"] == "PREPARED"
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    recovered = module.recover_release(str(pending[0][0]["txn_id"]))
    assert recovered["status"] in {"UPGRADED", "VERIFIED"}
    pointer = module._load_json(module._state_paths()["pointer"])
    assert pointer["active"]["release_id"] == world["target"]["release_id"]


def test_bootstrap_forward_upgrade_cli_absorbs_technical_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v2_forward_upgrade_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "_run_activation_canary",
        lambda journal: _canary_value(module, journal),
    )
    exit_code = module.main(["bootstrap-forward-upgrade"])
    assert exit_code == 0
    # Hidden fields rejected.
    exit_code = module.main(
        ["bootstrap-forward-upgrade", "--release-id", str(world["target"]["release_id"])]
    )
    assert exit_code == 2


def test_bootstrap_forward_upgrade_rejects_hidden_migration_fields_in_parser() -> None:
    module = _module()
    parser = module._parser()
    args = parser.parse_args(["bootstrap-forward-upgrade"])
    assert args.command == "bootstrap-forward-upgrade"
    with pytest.raises(module.XinaoError) as failure:
        parser.parse_args(["bootstrap-forward-upgrade", "--compat-release", "x"])
    assert failure.value.reason_code == "INVOCATION_ARGUMENTS_INVALID"


def _prepare_current_schema_source_drift_world(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    variant: bytes | None = b"same-version-source-bundle-drift\n",
    shadow_runtime_tree_sha256: str | None = None,
    shadow_runtime_lock_sha256: str | None = None,
) -> dict[str, object]:
    """Current-schema active with same package/cap versions as source but drifted identity.

    Models the live defect: schema generation is already exact-current and versions match
    source, yet sealed skill-bundle and/or shadow bytes lag the migration/forward-upgrade
    source cone. Without identity awareness, bootstrap-forward-upgrade would claim ALREADY_*.

    Does not prebuild or mock a same-semver target: formal prepare/build must refuse under
    SEMVER_CONTENT_COLLISION (or another precise source-ahead refusal) without mint/adopt.
    """

    source_identity = module._current_source_skill_bundle_identity()
    package_version = source_identity["package_version"]
    capability_version = source_identity["capability_version"]
    active, active_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="d",
        package_version=package_version,
        capability_version=capability_version,
        variant=variant,
        shadow_runtime_tree_sha256=shadow_runtime_tree_sha256,
        shadow_runtime_lock_sha256=shadow_runtime_lock_sha256,
    )
    assert active["package_version"] == package_version
    assert active["capability_version"] == capability_version
    assert module._active_release_requires_forward_upgrade(active) is True
    pointer, journal, journal_path = _terminal_pointer(
        module,
        active,
        active_path,
        generation=3,
        txn_suffix="b" * 16,
        previous_verified=None,
    )

    import shutil

    installed = tmp_path / "installed_skill_drift"
    if installed.exists():
        shutil.rmtree(installed)
    shutil.copytree(Path(str(active["skill_bundle_path"])), installed)
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(module, "DEFAULT_INSTALLED_SKILL_ROOT", installed)

    pointer_path = module._state_paths()["pointer"]
    return {
        "active": active,
        "active_path": active_path,
        "pointer": pointer,
        "pointer_path": pointer_path,
        "journal": journal,
        "journal_path": journal_path,
        "source_identity": source_identity,
        "installed": installed,
        "pointer_bytes": pointer_path.read_bytes(),
        "active_manifest_bytes": active_path.read_bytes(),
    }


def test_same_version_skill_bundle_drift_requires_forward_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    source = module._current_source_skill_bundle_identity()
    assert re.fullmatch(r"[0-9a-f]{64}", source["shadow_runtime_tree_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", source["shadow_runtime_lock_sha256"])
    matching, _path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        package_version=source["package_version"],
        capability_version=source["capability_version"],
    )
    assert matching["skill_bundle_tree_sha256"] == source["skill_bundle_tree_sha256"]
    assert (
        matching["source_identity"]["shadow_runtime_tree_sha256"]
        == source["shadow_runtime_tree_sha256"]
    )
    assert (
        matching["source_identity"]["shadow_runtime_lock_sha256"]
        == source["shadow_runtime_lock_sha256"]
    )
    assert module._active_release_requires_forward_upgrade(matching) is False

    drifted, _drifted_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="b",
        package_version=source["package_version"],
        capability_version=source["capability_version"],
        variant=b"future-same-version-byte-drift\n",
    )
    assert drifted["skill_bundle_tree_sha256"] != source["skill_bundle_tree_sha256"]
    assert drifted["package_version"] == source["package_version"]
    assert drifted["capability_version"] == source["capability_version"]
    assert module._active_release_requires_forward_upgrade(drifted) is True


def test_shadow_only_source_drift_requires_forward_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shadow-only drift must not look current even when skill tree/versions match.

    Active remains a fully sealed valid release (real tree/lock). Drift is modeled by
    advancing the migration-source shadow tree identity, not by forging SI tree hex
    (Wave91/95 tree recompute rejects forged trees under verify_bundle=True).
    """

    module = _module()
    source = module._current_source_skill_bundle_identity()
    matching, _path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        package_version=source["package_version"],
        capability_version=source["capability_version"],
    )
    assert matching["skill_bundle_tree_sha256"] == source["skill_bundle_tree_sha256"]
    assert module._active_release_requires_forward_upgrade(matching) is False

    drifted_source = dict(source)
    drifted_source["shadow_runtime_tree_sha256"] = "f" * 64
    assert drifted_source["shadow_runtime_tree_sha256"] != source["shadow_runtime_tree_sha256"]
    monkeypatch.setattr(module, "_current_source_skill_bundle_identity", lambda: drifted_source)
    assert matching["skill_bundle_tree_sha256"] == drifted_source["skill_bundle_tree_sha256"]
    assert matching["package_version"] == drifted_source["package_version"]
    assert matching["capability_version"] == drifted_source["capability_version"]
    assert (
        matching["source_identity"]["shadow_runtime_tree_sha256"]
        != drifted_source["shadow_runtime_tree_sha256"]
    )
    assert module._active_release_requires_forward_upgrade(matching) is True


def test_bootstrap_forward_upgrade_same_semver_source_drift_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same package+capability with different sealed bytes must never mint/adopt.

    Formal prepare/build surfaces SEMVER_CONTENT_COLLISION; pointer and the existing
    same-semver release remain byte-identical. Version-bumped source upgrades via the
    separate legal immutable bump path (package 1.3.6 / capability 1.2.2).
    """

    module = _module()
    world = _prepare_current_schema_source_drift_world(module, tmp_path, monkeypatch)
    assert module._active_release_requires_forward_upgrade(world["active"]) is True
    assert world["active"]["package_version"] == world["source_identity"]["package_version"]
    assert world["active"]["capability_version"] == world["source_identity"]["capability_version"]
    assert (
        world["active"]["skill_bundle_tree_sha256"]
        != world["source_identity"]["skill_bundle_tree_sha256"]
    )
    release_root = module._state_paths()["release_root"]
    releases_before = {
        path.name: (path / "release.json").read_bytes()
        for path in sorted(release_root.iterdir())
        if path.is_dir() and (path / "release.json").is_file()
    }
    _fake_build_environment(module, monkeypatch, dirty=False, image_character="f")
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_forward_upgrade()
    assert failure.value.reason_code == "SEMVER_CONTENT_COLLISION"
    assert world["pointer_path"].read_bytes() == world["pointer_bytes"]
    assert Path(str(world["active_path"])).read_bytes() == world["active_manifest_bytes"]
    pointer = module._load_json(world["pointer_path"])
    assert pointer["active"]["release_id"] == world["active"]["release_id"]
    assert not any(
        status in {"ALREADY_CURRENT", "ALREADY_UPGRADED", "UPGRADED"}
        for status in [failure.value.reason_code]
    )
    releases_after = {
        path.name: (path / "release.json").read_bytes()
        for path in sorted(release_root.iterdir())
        if path.is_dir() and (path / "release.json").is_file()
    }
    assert releases_after == releases_before


def test_bootstrap_forward_upgrade_same_version_drift_never_claims_already(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative: drifted current-schema active must not return ALREADY_*."""

    module = _module()
    world = _prepare_current_schema_source_drift_world(module, tmp_path, monkeypatch)
    # prepare returns None (as when build fence says not required / no target). Drift gate
    # must still refuse ALREADY_* and surface TARGET_ABSENT instead of silent current.
    monkeypatch.setattr(module, "_prepare_forward_upgrade_target", lambda: None)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_forward_upgrade()
    assert failure.value.reason_code == "FORWARD_UPGRADE_TARGET_ABSENT"
    pointer = module._load_json(world["pointer_path"])
    assert pointer["active"]["release_id"] == world["active"]["release_id"]
    assert world["pointer_path"].read_bytes() == world["pointer_bytes"]


def test_bootstrap_forward_upgrade_shadow_only_drift_never_claims_already(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shadow-only source drift must not return ALREADY_* without pointer mutation.

    Seals a valid active (real shadow tree + matching skill tree), then advances only the
    migration-source shadow tree so skill-bundle still matches while shadow-only drift
    forces upgrade. Forged SI tree hex is no longer a legal sealed fixture (Wave91 A1b).
    """

    module = _module()
    source_identity = module._current_source_skill_bundle_identity()
    package_version = source_identity["package_version"]
    capability_version = source_identity["capability_version"]
    active, active_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="d",
        package_version=package_version,
        capability_version=capability_version,
        variant=None,
    )
    assert active["skill_bundle_tree_sha256"] == source_identity["skill_bundle_tree_sha256"]
    assert module._active_release_requires_forward_upgrade(active) is False
    pointer, journal, journal_path = _terminal_pointer(
        module,
        active,
        active_path,
        generation=3,
        txn_suffix="b" * 16,
        previous_verified=None,
    )
    import shutil

    installed = tmp_path / "installed_skill_shadow_drift"
    if installed.exists():
        shutil.rmtree(installed)
    shutil.copytree(Path(str(active["skill_bundle_path"])), installed)
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(module, "DEFAULT_INSTALLED_SKILL_ROOT", installed)
    pointer_path = module._state_paths()["pointer"]
    pointer_bytes = pointer_path.read_bytes()

    drifted_source = dict(source_identity)
    drifted_source["shadow_runtime_tree_sha256"] = "e" * 64
    assert (
        active["source_identity"]["shadow_runtime_tree_sha256"]
        != drifted_source["shadow_runtime_tree_sha256"]
    )
    monkeypatch.setattr(module, "_current_source_skill_bundle_identity", lambda: drifted_source)
    assert module._active_release_requires_forward_upgrade(active) is True
    monkeypatch.setattr(module, "_prepare_forward_upgrade_target", lambda: None)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_forward_upgrade()
    assert failure.value.reason_code == "FORWARD_UPGRADE_TARGET_ABSENT"
    assert pointer_path.read_bytes() == pointer_bytes
    del journal, journal_path  # constructed for realistic terminal pointer world
