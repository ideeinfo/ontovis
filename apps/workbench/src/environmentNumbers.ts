export const environmentNumbers={
  exposure:{min:.25,max:2.5,note:['1为基准；越大越亮，资料原色影像保持原色。','1 is the baseline; higher is brighter. Source-color imagery stays unchanged.']},
  azimuth:{min:0,max:360,exclusive:true,note:['朝向太阳的方位：北0°、东90°。','Bearing toward the sun: north 0°, east 90°.']},
  elevation:{min:5,max:85,note:['越高阴影越短；关闭太阳后不生效。','Higher sun produces shorter shadows; requires the sun.']},
  intensity:{min:0,max:5,note:['0关闭直射光；仅为视觉强度。','0 disables direct light; this is a visual intensity.']},
  ambient:{min:0,max:5,note:['调整整体明暗基调，0关闭半球光。','Sets overall fill light; 0 disables hemisphere light.']},
  environment:{min:0,max:3,note:['调整天空带来的环境照明和材质反光。','Controls sky-based illumination and material reflections.']},
  near:{min:0,max:100000,note:['开始起雾的相机视距；须小于雾终点。','Camera distance where fog starts; must be below fog far.']},
  far:{min:0,max:100000,note:['完全融入地平线颜色的视距；须大于起点。','Camera distance at full fog; must exceed fog near.']},
  radius:{min:100,max:1000,note:['仅在当前关注区域计算阴影，半径越大覆盖越广。','Shadows cover the current area of interest within this radius.']},
  rough:{min:.2,max:1,note:['越大越哑光；仅作用于未被覆盖的地表。','Higher is more matte; affects uncovered ground only.']},
  repeat:{min:1,max:200,note:['草纹每次重复的实际长度；仅草纹地表生效。','Ground distance per grass tile; applies to grass ground only.']},
  direction:{min:0,max:360,exclusive:true,note:['波纹移向的方位：北0°、东90°，不是风向来源。','Ripple travel toward north 0° or east 90°; not wind-from direction.']},
  strength:{min:0,max:1,note:['0为平静；越大细节越明显，不代表实际波高。','0 is calm; higher adds detail, not physical wave height.']},
  length:{min:5,max:200,note:['波纹的视觉尺度，越大越舒展。','Visual ripple scale; larger values spread the pattern out.']},
  speed:{min:0,max:5,note:['0为静止；只改变视觉动画，不移动设备。','0 is still; affects visual animation, not equipment placement.']},
  waterRough:{min:.1,max:1,note:['越小反光越集中，越大越哑光。','Lower produces sharper highlights; higher is more matte.']},
} as const;
export type EnvironmentNumberKey=keyof typeof environmentNumbers;
export function environmentNumberValid(key:EnvironmentNumberKey,value:number){
  const rule=environmentNumbers[key];
  return Number.isFinite(value)&&value>=rule.min&&('exclusive' in rule?value<rule.max:value<=rule.max);
}
export function environmentNumberRange(key:EnvironmentNumberKey){
  const rule=environmentNumbers[key];return `${rule.min}–${'exclusive' in rule?'<':''}${rule.max}`;
}
