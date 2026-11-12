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
// Added from the Life-Study development set (2026-11-12, scripts/mine-same-sound-terms.mjs): each fixed recognizer
// errors there (神的經論→神的經綸, 西安山→錫安山, 定十字架→釘十字架…) and changed at most a few places in the whole
// Recovery Version + Life-Study text. Chosen on development data only, never on the sealed MEET test. Left out after
// checking everyday phrases: 神的國 (神的果子→神的國子), 美地 (每地方→美地方).
export const LIFE_STUDY_TERMS = ['神的經綸', '神經綸', '神的形像', '神的管治', '錫安山', '爭戰', '豫表',
  '釘十字架', '奧祕', '受膏者', '瑪代', '遮覆', '罩蓋', '成孕', '揀選', '細麻衣', '掠物', '迦勒底人', '哈巴谷',
  '提摩太', '亞捫人', '異象', '錫安', '公義', '實化'];
import {BIBLE_NAMES} from './bible-names.js';
export {BIBLE_NAMES};
// Books + core church terms (the set evaluated first); DEFAULT_TERMS also includes Bible person/place names.
export const CORE_DEFAULT_TERMS = [...new Set([...BIBLE_BOOKS, ...CORE_TERMS, ...LIFE_STUDY_TERMS])];
export const DEFAULT_TERMS = [...new Set([...CORE_DEFAULT_TERMS, ...BIBLE_NAMES])];

