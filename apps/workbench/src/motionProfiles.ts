export interface MotionProfile {
 nodes:number;layout:'grouped'|'baked';movingStart:number;movingEnd:number;rotorStart:number;rotorEnd:number;
 hubHeight:number;rotorZ:number;rpm:[number,number];
}
export const MOTION_MODEL_SHA='078bbc161a9c9c8cbe0bbc872ca825b6a222d4d4c22f8c16c7889908a97a5806';
export const MOTION_MERGED_SHA='fb7963a94988d67a16c5ef08c024b200881df53d4f4e2e2cde27661861d9d9b1';
const grouped=(nodes:number,movingEnd:number,rotorStart:number,rotorEnd:number):MotionProfile=>({nodes,layout:'grouped',movingStart:12,movingEnd,rotorStart,rotorEnd,hubHeight:90,rotorZ:6.67,rpm:[6,10]});
const baked=(nodes:number,movingStart:number,rotorStart:number,rotorEnd:number,hubHeight:number,rotorZ:number,rpm:[number,number]):MotionProfile=>({nodes,layout:'baked',movingStart,movingEnd:rotorStart-1,rotorStart,rotorEnd,hubHeight,rotorZ,rpm});
// Fixed-content teaching models. Pivots come from the source zero pose, not the asymmetrical hub bounds.
const profiles:Record<string,MotionProfile>={
 [MOTION_MODEL_SHA]:grouped(20,14,15,19),[MOTION_MERGED_SHA]:grouped(184,142,143,175),
 '94faced193391ad68d79f2d6779acdc7e949b97aa571d82d704c275393390506':grouped(20,14,15,19),
 'e5fecd93d0fe846883be50fd6b8b89cede9f6739d4fe7a83d3f9e918f4348c7d':baked(41,18,36,40,74,6.214,[7,11]),
 '40aa13d46bc60f3c7ba4120ed900d591ded5c120ac08833dab4e9df71e96bcfe':baked(71,34,61,70,120,8.2,[5,8]),
 'e1c6381f7307d8e607d85a5b665f9ba5a0d882484ed85625206210d221c0a24c':baked(62,18,41,61,73.5,5.248,[6,10]),
 'f20a7d1af9ca22e937fea7ed3144f7889139556a97add866bb5f2ee4c8e90cf1':baked(57,33,49,56,80,6.7,[7,11]),
 '4eff3bb556859105e5f9e44930a6aba8bd4c1e91d6871473534fdcc63b983488':baked(45,15,36,44,60,5.09,[11,14]),
 'cca1b148de90c066aaab914d2e5cf152772c14615bee3ac64cb7a2beb44605bb':baked(43,21,37,42,68.5,6.7,[7,11]),
 'a23e4a7ff9782c673047fefbb3a1b65f1e025cef697994458c9f4d10464b29fa':baked(72,33,62,71,83.5,5.55,[6,9]),
 '8ea2286721fe0cdabbce0d108bc4017d5a5a502c552e438620bd5ea0560c036f':baked(73,33,61,71,113,9.75,[5,8]),
 'eef5021e574fa340d89872882cae4502b6ed793a58c42200a2cedf2458258cc0':baked(56,31,51,55,150,10.58,[4,7]),
 'a66c18148339ea3d1a4d1f0852a2c8201e48df05a9e2f2df8e4a65acb75886bb':baked(78,23,67,70,170,12.58,[4,6]),
};
export const motionProfile=(sha:string):MotionProfile|null=>profiles[sha]??null;
