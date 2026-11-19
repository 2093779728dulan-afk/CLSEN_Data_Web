import { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlow, Handle, Position, type Node, type NodeProps, type Edge, useReactFlow, ReactFlowProvider } from "@xyflow/react";
import { CheckCircle2, CircleDot, CircleHelp, Circle, TriangleAlert } from "lucide-react";
import dagre from "@dagrejs/dagre";
import type { TraceGraph, TraceNode } from "./productionTrace";
import "@xyflow/react/dist/style.css";
import styles from "./ProductionProgressFlow.module.css";

type FlowNode = Node<{trace:TraceNode; open:(node:TraceNode, trigger:HTMLElement)=>void; vertical:boolean; height:number; width:number; quantityHeight:number}, "progress">;
function ProgressNode({data}:NodeProps<FlowNode>) {
  const {trace,vertical,height,width,quantityHeight}=data;
  const StateIcon={done:CheckCircle2,partial:CircleDot,unknown:CircleHelp,idle:Circle}[trace.tone];
  const status=trace.status==="尚未登记 / 待核"?"未登记":trace.status;
  return <><Handle type="target" position={vertical?Position.Top:Position.Left}/><button data-trace-node-id={trace.id} className={`${styles.node} ${styles[trace.tone]}`} style={{minHeight:height,width}} title={[trace.status,trace.location].filter(Boolean).join(" · ")} aria-label={`${trace.title}，${trace.quantity}，${trace.status}${trace.percent!==undefined?`，逐规格完成 ${trace.percent}%`:""}${trace.warning?`，${trace.warning}`:""}${trace.stage==="order"?`，款号 ${trace.styleCodes?.join("、")||"待核"}`:""}`} onClick={event=>data.open(trace,event.currentTarget)}>
    <strong title={trace.title}>{trace.title}</strong><span className={styles.nodeQuantity} style={{minHeight:quantityHeight}}>{trace.quantity}</span>
    <span className={styles.nodeState}>{trace.percent!==undefined?<span className={styles.percent} title={`按规格完成 ${trace.percent}%`}>{trace.percent}%</span>:<span className={styles.stateBadge} title={trace.status}><StateIcon size={13} aria-hidden="true"/>{status}</span>}</span>
    {trace.percent!==undefined&&<progress className={styles.nodeProgress} aria-label={`${trace.title}逐规格完成度`} max={100} value={trace.percent}/>}
    {trace.stage==="order"&&<small className={styles.nodeStyles} title={`款号 ${trace.styleCodes?.join("、")||"待核"}`}>款号 {trace.styleCodes?.join("、")||"待核"}</small>}
    {trace.warning&&<small className={styles.warning}><TriangleAlert size={12} aria-hidden="true"/>{trace.warning}</small>}
  </button><Handle type="source" position={vertical?Position.Bottom:Position.Right}/></>;

}
const nodeTypes={progress:ProgressNode};
function Canvas({graph,onOpen,label}:{graph:TraceGraph;onOpen:(node:TraceNode,trigger:HTMLElement)=>void;label:string}) {
  const [vertical,setVertical]=useState(()=>window.matchMedia("(max-width: 700px)").matches);
  useEffect(()=>{const m=window.matchMedia("(max-width: 700px)");const change=()=>setVertical(m.matches);m.addEventListener("change",change);return()=>m.removeEventListener("change",change);},[]);
  const flow=useReactFlow();const canvas=useRef<HTMLDivElement>(null);const [width,setWidth]=useState(0);
  useEffect(()=>{const element=canvas.current?.parentElement;if(!element)return;const observer=new ResizeObserver(()=>setWidth(element.clientWidth));observer.observe(element);setWidth(element.clientWidth);return()=>observer.disconnect();},[]);
  const stacked=vertical;
  const {nodes,edges,bounds}=useMemo(()=>{
    const nodeWidth=!stacked&&graph.nodes.length>3&&width>0?Math.max(136,Math.min(168,Math.floor((width-40-(graph.nodes.length-1)*16)/graph.nodes.length))):168;
    const layout=new dagre.graphlib.Graph().setDefaultEdgeLabel(()=>({}));layout.setGraph({rankdir:stacked?"TB":"LR",nodesep:24,ranksep:graph.nodes.length>3?16:24,marginx:8,marginy:8});
    const quantityHeight=Math.max(22,...graph.nodes.map(n=>Math.ceil([...n.quantity].reduce((sum,char)=>sum+(char.charCodeAt(0)>255?16:9),0)/(nodeWidth-18))*22));
    const height=Math.max(96,...graph.nodes.map(n=>88+(quantityHeight-22)+(n.percent!==undefined?8:0)+(n.stage==="order"?24:0)+(n.warning?24:0)));
    graph.nodes.forEach(n=>layout.setNode(n.id,{width:nodeWidth,height}));graph.edges.forEach(e=>layout.setEdge(e.source,e.target));dagre.layout(layout);
    const nodes:FlowNode[]=graph.nodes.map(n=>{const pos=layout.node(n.id) as {x:number;y:number;width:number;height:number};return {id:n.id,type:"progress",position:{x:pos.x-pos.width/2,y:pos.y-pos.height/2},data:{trace:n,open:onOpen,vertical:stacked,height,width:nodeWidth,quantityHeight},draggable:false,connectable:false,focusable:false};});
    const edges:Edge[]=graph.edges.map(e=>({id:e.id,source:e.source,target:e.target,label:e.quantity,style:{strokeDasharray:e.planned?"4 4":undefined},ariaLabel:`${e.planned?"计划，尚无实际记录":"已证实关联"}：${e.evidence}`,markerEnd:{type:"arrowclosed" as const}}));const dimensions=layout.graph() as {width?:number;height?:number};return {nodes,edges,bounds:{width:dimensions.width||0,height:dimensions.height||0}};
  },[graph,onOpen,stacked,width]);
  useEffect(()=>{
    if(!width||!bounds.width)return;
    let second=0;const first=requestAnimationFrame(()=>{second=requestAnimationFrame(()=>{void flow.setViewport({x:stacked?(width-bounds.width)/2:8,y:4,zoom:1});});});
    return()=>{cancelAnimationFrame(first);cancelAnimationFrame(second);};
  },[stacked,width,bounds.width,bounds.height,flow]);
  return <div className={styles.chain} role="region" aria-label={label} tabIndex={0}><div ref={canvas} className={styles.canvas} style={{height:bounds.height+8,minWidth:bounds.width+16}}><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false} edgesFocusable={false} zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false} panOnDrag={false} panOnScroll={false} preventScrolling={false} autoPanOnNodeFocus={false} minZoom={1} maxZoom={1} proOptions={{hideAttribution:true}}/></div></div>;


}
export function ProductionProgressFlow(props: {graph:TraceGraph;onOpen:(node:TraceNode,trigger:HTMLElement)=>void;label:string}) {return <ReactFlowProvider><Canvas {...props}/></ReactFlowProvider>;}
