// Built-in same-sound correction terms (data only; scripts/build-pinyin-table.py precomputes their readings).
// Hosts add more in the glossary box: one term per line, without "=".
// Everyday words (重生、救贖、調和) are left out on purpose: recognizers usually get them right, and their
// same-sound neighbours are normal text (眾生、就贖出、規條和), so correcting them causes false edits.
export const BIBLE_BOOKS = ['創世記', '出埃及記', '利未記', '民數記', '申命記', '約書亞記', '士師記', '路得記',
  '撒母耳記上', '撒母耳記下', '列王紀上', '列王紀下', '歷代志上', '歷代志下', '以斯拉記', '尼希米記', '以斯帖記',
  '約伯記', '詩篇', '箴言', '傳道書', '雅歌', '以賽亞書', '耶利米書', '耶利米哀歌', '以西結書', '但以理書', '何西阿書',
  '約珥書', '阿摩司書', '俄巴底亞書', '約拿書', '彌迦書', '那鴻書', '哈巴谷書', '西番雅書', '哈該書', '撒迦利亞書',
  '瑪拉基書', '馬太福音', '馬可福音', '路加福音', '約翰福音', '使徒行傳', '羅馬書', '哥林多前書', '哥林多後書',
  '加拉太書', '以弗所書', '腓立比書', '歌羅西書', '帖撒羅尼迦前書', '帖撒羅尼迦後書', '提摩太前書', '提摩太後書',
  '提多書', '腓利門書', '希伯來書', '雅各書', '彼得前書', '彼得後書', '約翰壹書', '約翰貳書', '約翰參書', '猶大書', '啟示錄'];
export const CORE_TERMS = ['耶穌基督', '保羅', '亞伯拉罕', '耶路撒冷', '加利利', '哥林多', '經綸', '那靈', 
  '配搭', '擘餅', '禱告', '生命讀經', '恢復本', '召會', '召會生活', '介言', '申言', '申言者',
  '以馬內利', '哈利路亞', '新耶路撒冷', '三一神', '基督的身體'];
import {BIBLE_NAMES} from './bible-names.js';
export {BIBLE_NAMES};
// Books + core church terms (the set evaluated first); DEFAULT_TERMS also includes Bible person/place names.
export const CORE_DEFAULT_TERMS = [...new Set([...BIBLE_BOOKS, ...CORE_TERMS])];
export const DEFAULT_TERMS = [...new Set([...CORE_DEFAULT_TERMS, ...BIBLE_NAMES])];

