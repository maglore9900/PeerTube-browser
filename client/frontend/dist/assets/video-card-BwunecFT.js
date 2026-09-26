import{s as x}from"./safe-url-Bow8sMhM.js";const N=new Intl.NumberFormat("en-US");function l(n){return n.replace(/[&<>"']/g,e=>{switch(e){case"&":return"&amp;";case"<":return"&lt;";case">":return"&gt;";case'"':return"&quot;";case"'":return"&#39;";default:return e}})}function S(n){return n.instance_domain??n.instanceDomain??""}function A(n){const e=n.video_uuid??n.videoUuid??n.video_id??"";return e?String(e):""}function D(n){const e=S(n),t=A(n);return!e||!t?null:`${e}::${t}`}function I(n){return n.thumbnail_url??n.thumbnailUrl??n.preview_path??n.previewPath??null}function v(n){return n.channel_display_name??n.channelDisplayName??n.channel_name??n.channelName??"Unknown channel"}function V(n){const e=v(n).trim();if(!e)return"•";const a=e.replace(/[_\-]+/g," ").replace(/\s+/g," ").trim().split(" ").filter(Boolean);return a.length===1?a[0].slice(0,2).toUpperCase():`${a[0][0]}${a[1][0]}`.toUpperCase()}function C(n){return n.channel_avatar_url??n.channelAvatarUrl??n.account_avatar_url??n.accountAvatarUrl??n.avatar_url??n.avatarUrl??null}function p(n){if(n.channel_url)return n.channel_url;if(n.channelUrl)return n.channelUrl;const e=n.channel_name??n.channelName,t=n.instance_domain??n.instanceDomain;return e&&t?`https://${t}/video-channels/${encodeURIComponent(e)}`:"#"}function F(n){if(n.video_url)return n.video_url;if(n.videoUrl)return n.videoUrl;const e=n.video_uuid??n.videoUuid,t=n.instance_domain??n.instanceDomain;return e&&t?`https://${t}/videos/watch/${encodeURIComponent(e)}`:"#"}function P(n){const e=n.embed_path??n.embedPath??"";if(e.startsWith("http"))return e;const t=n.instance_domain??n.instanceDomain;if(e&&t)return`https://${t}${e}`;const a=n.video_uuid??n.videoUuid;return a&&t?`https://${t}/videos/embed/${encodeURIComponent(a)}`:""}function H(n){const e=n.published_at??n.publishedAt??null;if(!e||!Number.isFinite(e))return null;const t=Number(e);return t<1e12?t*1e3:t}function B(n){const e=Date.now(),t=Math.max(0,e-n),a=60*1e3,s=60*a,i=24*s,r=30*i,c=365*i;return t<a?"just now":t<s?`${Math.floor(t/a)} minutes ago`:t<i?`${Math.floor(t/s)} hours ago`:t<r?`${Math.floor(t/i)} days ago`:t<c?`${Math.floor(t/r)} months ago`:`${Math.floor(t/c)} years ago`}function R(n){if(!n||!Number.isFinite(n))return"0:00";const e=Math.max(0,Math.round(n)),t=Math.floor(e/3600),a=Math.floor(e%3600/60),s=e%60;return t>0?`${t}:${String(a).padStart(2,"0")}:${String(s).padStart(2,"0")}`:`${a}:${String(s).padStart(2,"0")}`}function o(n){return n==null||!Number.isFinite(n)?"--":N.format(n)}function K(n){if(n==null)return null;const e=Number(n);return Number.isFinite(e)?e:null}function z(){return`
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 11v9M7 20h7.3a2 2 0 0 0 1.95-1.55l1.7-7A2 2 0 0 0 16 9H12V5a2 2 0 0 0-2-2l-3 6" />
      <rect x="3" y="11" width="4" height="9" rx="1.2" />
    </svg>
  `}function E(){return`
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 13V4M7 4h7.3a2 2 0 0 1 1.95 1.55l1.7 7A2 2 0 0 1 16 15h-4v4a2 2 0 0 1-2 2l-3-6" />
      <rect x="3" y="4" width="4" height="9" rx="1.2" />
    </svg>
  `}function L(n,e){const t=new URLSearchParams,a=n.instance_domain??n.instanceDomain??"",s=n.video_id??n.video_uuid??n.videoUuid??"";s&&t.set("id",s),a&&t.set("host",a),n.title&&t.set("title",n.title);const i=n.channel_display_name??n.channelDisplayName??n.channel_name??n.channelName??"";i&&t.set("channel",i);const r=p(n);r&&r!=="#"&&t.set("channelUrl",r);const c=P(n);c&&t.set("embed",c);const u=F(n);return u&&u!=="#"&&t.set("url",u),`/video-page.html?${t.toString()}`}function j(n,e={}){const t=n.title??"Untitled video",a=I(n),s=R(n.duration??null),i=e.stats??null,r=(i==null?void 0:i.views)??null,c=(i==null?void 0:i.likes)??null,u=(i==null?void 0:i.dislikes)??null,$=v(n),b=p(n),d=C(n),_=V(n),h=H(n),f=h?B(h):null,g=f?` · ${f}`:"",U=d?`<img src="${l(d)}" alt="" loading="lazy" />`:`<span>${l(_)}</span>`,M=a?`<img src="${l(a)}" alt="${l(t)}" loading="lazy" />`:'<div class="thumb-fallback">No preview</div>',m=D(n),k=m?` data-video-key="${l(m)}"`:"",y=e.footerExtraHtml??"";return`
    <article class="video-card"${k}>
      <a class="video-link" href="${l(L(n,e.apiParam))}">
        <div class="video-thumb">
          ${M}
          <span class="duration">${s}</span>
        </div>
        <div class="video-body">
          <h3 class="video-title">${l(t)}</h3>
          <div class="video-footer">
            <div class="channel-meta">
              <div class="channel-avatar" aria-hidden="true">${U}</div>
              <div class="channel-text">
                <a class="channel-link" href="${l(x(b))}" target="_blank" rel="noreferrer">
                  ${l($)}
                </a>
                <div class="video-meta"><span data-stat="views">${o(r)}</span> views${l(g)}</div>
              </div>
            </div>
            <div class="video-stats">
              <span class="stat likes">${z()}<span data-stat="likes">${o(c)}</span></span>
              <span class="stat dislikes">${E()}<span data-stat="dislikes">${o(u)}</span></span>
            </div>
            ${y}
          </div>
        </div>
      </a>
    </article>
  `}export{D as a,S as b,A as c,v as d,l as e,o as f,K as n,j as r,I as t,L as v};
