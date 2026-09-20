const API = "http://127.0.0.1:18765";
const MARKETS = new Set(["amazon.com","amazon.co.uk","amazon.de","amazon.co.jp","amazon.com.au"]);
let busy = false;
async function note(message) { await chrome.storage.local.set({lastMessage:message}); }
async function rpc(path, payload={}) {
  const settings = await chrome.storage.local.get(["token", "client"]);
  if (!settings.token) throw new Error("请先粘贴 PM Stack 连接码");
  const response = await fetch(API + path, {method:"POST",
    headers:{"Content-Type":"application/json", Authorization:"Bearer " + settings.token},
    body:JSON.stringify({...payload, client:settings.client}), signal:AbortSignal.timeout(10000)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "PM Stack 连接失败");
  return data;
}
function validJob(job) {
  if (!MARKETS.has(job.marketplace) || !/^[A-Z0-9]{10}$/.test(job.asin) || !/^[a-f0-9]{32}$/.test(job.id))
    throw new Error("采集任务格式不正确");
  const url = new URL(job.url);
  if (url.origin !== "https://www." + job.marketplace || url.pathname !== "/product-reviews/" + job.asin + "/")
    throw new Error("任务链接不属于指定商品");
}
async function scan(job, active) {
  let tab;
  try { tab = await chrome.tabs.get(active.tabId); }
  catch { await rpc("/result", {id:job.id, status:"error", message:"采集标签页已关闭，请重新提交任务"}); return; }
  if (tab.status !== "complete") return;
  const url = new URL(tab.url || "about:blank");
  if (url.origin !== "https://www." + job.marketplace) {
    // Never inject into another site or alter a tab the user navigated elsewhere.
    await rpc("/result", {id:job.id, status:"error", message:"采集标签页已离开指定 Amazon 站点，请重新提交任务"});
    return;
  }
  for (let attempt=0; attempt<8; attempt++) {
    const values = await chrome.scripting.executeScript({target:{tabId:active.tabId},files:["extract.js"]});
    const data = values[0]?.result;
    if (!data) throw new Error("页面读取失败");
    if (data.status === "waiting") {
      await rpc("/result", {id:job.id, ...data});
      await note(data.message);
      return;
    }
    // After sign-in Amazon may land on a different page. Return to the requested reviews once.
    if (url.pathname.replace(/\/$/, "") !== "/product-reviews/" + job.asin) {
      if (job.status === "waiting") { await chrome.tabs.update(active.tabId, {url:job.url}); return; }
      await rpc("/result", {id:job.id, status:"error", message:"页面未停留在指定商品评论页，请重新提交任务"});
      return;
    }
    if (data.status === "ready") {
      const saved = await rpc("/result", {id:job.id, ...data});
      await note(saved.job.message);
      return;
    }
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  const message = "未识别到评论：可能没有评论、页面尚未开放或页面结构已变化；未写入数据。";
  await rpc("/result", {id:job.id, status:"error", message});
  await note(message);
}
async function tick() {
  if (busy) return {message:"正在处理任务，请稍候"};
  busy = true;
  try {
    const {job} = await rpc("/poll");
    if (!job || ["done","error","cancelled"].includes(job.status)) {
      await chrome.storage.session.remove("active");
      const message = job?.message || "已连接 PM Stack，等待采集任务";
      await note(message);
      return {message};
    }
    validJob(job);
    let {active} = await chrome.storage.session.get(["active"]);
    if (!active || active.id !== job.id) {
      const tab = await chrome.tabs.create({url:"about:blank", active:true});
      active = {id:job.id, tabId:tab.id};
      await chrome.storage.session.set({active});
      await chrome.tabs.update(tab.id, {url:job.url});
      await note("正在打开评论页");
    } else {
      await scan(job, active);
    }
    return {message:(await chrome.storage.local.get(["lastMessage"])).lastMessage || "任务已开始"};
  } catch (error) {
    const message = "连接或读取失败：" + error.message;
    await note(message);
    return {message};
  } finally { busy=false; }
}
async function schedule() {
  const {token} = await chrome.storage.local.get(["token"]);
  if (token) await chrome.alarms.create("pm-stack-poll", {periodInMinutes:0.5});
}
chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.alarms.onAlarm.addListener(alarm=> {if(alarm.name==="pm-stack-poll") tick();});
chrome.tabs.onUpdated.addListener(async (id, change) => {
  if (change.status !== "complete") return;
  const {active} = await chrome.storage.session.get(["active"]);
  if (active?.tabId === id) tick();
});
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  // Only the extension's own popup can manage pairing, never a webpage.
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL("popup.html")) return false;
  (async () => {
    if (message.type === "CONNECT") {
      if (!/^[A-Za-z0-9_-]{40,80}$/.test(message.token || "")) return {message:"请粘贴完整连接码"};
      const {client} = await chrome.storage.local.get(["client"]);
      await chrome.storage.local.set({token:message.token, client:client || crypto.randomUUID()});
      await schedule();
      return tick();
    }
    if (message.type === "DISCONNECT") {
      await chrome.alarms.clear("pm-stack-poll");
      await chrome.storage.local.remove(["token"]);
      await chrome.storage.session.remove("active");
      await note("已断开扩展；如有任务，请在 PM Stack 取消");
      return {message:"已断开扩展"};
    }
    if (message.type === "CHECK") return tick();
    return {message:"未知操作"};
  })().then(respond).catch(error=>respond({message:error.message}));
  return true;
});
