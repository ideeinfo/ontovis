import {useEffect,useId,useRef,useState} from 'react';
import {environmentNumbers,environmentNumberRange,environmentNumberValid,type EnvironmentNumberKey} from './environmentNumbers';

export function EnvironmentNumberField(props:{name:EnvironmentNumberKey;label:string;value:number;locale:string;reset:number;disabled?:boolean;onValue:(value:number)=>void;onInvalid:(invalid:boolean)=>void}){
  const id=useId(),events=useRef(props);events.current=props;
  const [raw,setRaw]=useState(String(props.value)),[invalid,setInvalid]=useState(false);
  useEffect(()=>{setRaw(String(props.value));setInvalid(false);events.current.onInvalid(false);},[props.value,props.reset,props.disabled]);
  useEffect(()=>()=>events.current.onInvalid(false),[]);
  const rule=environmentNumbers[props.name],english=props.locale==='en';
  return <label className="ev-number"><span id={`${id}-label`}>{props.label}</span><input type="number" step="any" min={rule.min} max={rule.max}
    value={raw} disabled={props.disabled} aria-invalid={invalid||undefined} aria-labelledby={`${id}-label`} aria-describedby={id}
    onChange={event=>{const text=event.currentTarget.value,value=event.currentTarget.valueAsNumber,valid=text.trim()!==''&&environmentNumberValid(props.name,value);
      setRaw(text);setInvalid(!valid);props.onInvalid(!valid);if(valid)props.onValue(value);}}/>
    <small id={id}>{english?'Range':'范围'} {environmentNumberRange(props.name)} · {rule.note[english?1:0]}</small>
    {invalid&&<small className="ev-field-error" role="alert">{english?'Enter a value within the range.':'请输入范围内的数值。'}</small>}
  </label>;
}
