import { FormField } from "../../design-system";
import provinceCities from "./chinaProvinceCities.json";
import styles from "./DirectoryWorkspace.module.css";

const divisions: Record<string, string[]> = provinceCities;
const names = new Intl.DisplayNames(["zh-Hans"], { type: "region" });
const countryCodes = "CN HK MO TW VN KH BD IN ID TH MY PH PK LK MM LA JP KR SG US CA MX BR GB DE FR IT ES PT NL BE PL CZ TR AE SA AU NZ ZA EG NG KE ET MA AR CL CO PE AT CH DK FI NO SE IE GR HU RO BG UA RU IL JO KW QA OM BH NP BT MV MN KZ UZ GE AM AZ AF IR IQ SY LB YE TN DZ LY SD SS GH TZ UG RW CM SN CI AO MZ ZM ZW BW NA MU SC MG IS LU MT CY EE LV LT SI SK HR RS BA ME MK AL MD BY XK CU DO HT JM BS BB TT CR PA GT HN NI SV BZ EC BO PY UY VE GY SR FJ PG SB VU WS TO TV NR KI FM MH PW TL BN KP PS AD MC SM VA LI LC VC GD AG DM KN CV ST GQ GA CG CD CF TD NE ML BF BJ TG SL LR GN GW GM MR SO DJ ER KM SZ LS MW BI BQ CW SX AW BM GL FO GI IM JE GG AI MS TC VG VI PR GU AS MP PF NC CK NU PN TK WF PM BL MF AX IO CC CX NF HM AQ TF GS BV EH FK SH UM".split(" ");
// eslint-disable-next-line react-refresh/only-export-components -- Shared directory choices use the existing country list.
export const countries = [...new Set(countryCodes.map(code => code === "CN" ? "中国" : names.of(code)!))];

// Keep the existing region-string API. Only our exact selectable values are parsed;
// legacy free text is never normalized by an unrelated profile edit.
export function FactoryRegionPicker({ value, onChange, fixedCountry }: { value: string; onChange: (region: string) => void; fixedCountry?: string }) {
  const parts = value.split(" / ");
  const country = parts[0] || "";
  const province = parts[1] || "";
  const city = parts[2] || "";
  const known = !value || (countries.includes(country) && (country === "中国"
    ? parts.length <= 3 && (!province || Object.hasOwn(divisions, province)) && (!city || divisions[province]?.includes(city))
    : parts.length === 1));
  const legacy = !known;
  return <div className={styles.regionBlock}>
    <div className={styles.regionGrid} data-fixed-country={!!fixedCountry}>
      {!fixedCountry && <FormField label="国家 / 地区"><select value={legacy ? "__legacy__" : country} onChange={e => onChange(e.target.value)}>
        {legacy && <option value="__legacy__" disabled>保留原地区</option>}
        <option value="">暂不填写</option>
        {countries.map(name => <option key={name} value={name}>{name}</option>)}
      </select></FormField>}
      {!legacy && country === "中国" && <>
        <FormField label="省 / 直辖市 / 自治区"><select value={province} onChange={e => onChange(["中国", e.target.value].filter(Boolean).join(" / "))}>
          <option value="">请选择省级地区</option>
          {Object.keys(divisions).map(name => <option key={name}>{name}</option>)}
        </select></FormField>
        <FormField label="城市 / 区县"><select disabled={!province} value={city} onChange={e => onChange(["中国", province, e.target.value].filter(Boolean).join(" / "))}>
          <option value="">{province ? "请选择城市 / 区县" : "请先选择省级地区"}</option>
          {(divisions[province] || []).map(name => <option key={name}>{name}</option>)}
        </select></FormField>
      </>}
    </div>
    {legacy && <button type="button" onClick={()=>onChange(fixedCountry||'')}>重新选择地区（当前：{value}）</button>}
  </div>;
}
