// In-page links glide to their section (800ms, ease-in-out) and land below the sticky header.
// With reduced motion they jump instantly. Links to other pages (e.g. /#rankings) are left to the browser,
// which lands below the header via section[id]{scroll-margin-top}.
(function(){
  const header=document.querySelector('header');
  const reduce=matchMedia('(prefers-reduced-motion: reduce)');
  const DURATION=800;
  const ease=t=>t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2; // easeInOutCubic
  let raf=null;
  const stop=()=>{if(raf){cancelAnimationFrame(raf);raf=null;}};
  // a user scrolling during the glide takes over
  ['wheel','touchstart','keydown'].forEach(ev=>addEventListener(ev,stop,{passive:true}));

  function glide(to){
    stop();
    const max=document.documentElement.scrollHeight-innerHeight;
    to=Math.max(0,Math.min(to,max));
    if(reduce.matches){scrollTo(0,to);return;}
    const from=scrollY,dist=to-from;
    if(Math.abs(dist)<1) return;
    const t0=performance.now();
    (function step(now){
      const p=Math.min(1,(now-t0)/DURATION);
      scrollTo(0,from+dist*ease(p));
      raf=p<1?requestAnimationFrame(step):null;
    })(t0);
  }

  document.addEventListener('click',e=>{
    if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey) return;
    const a=e.target.closest('a[href^="#"]'); if(!a) return;
    const id=decodeURIComponent(a.getAttribute('href').slice(1));
    const target=id?document.getElementById(id):null;
    if(id&&!target) return;
    e.preventDefault();
    if(!target){ // href="#": back to the top
      history.pushState(null,'',location.pathname+location.search);
      glide(0); return;
    }
    const headH=header?header.getBoundingClientRect().height:0;
    glide(target.getBoundingClientRect().top+scrollY-headH);
    history.pushState(null,'','#'+id);
    if(!target.hasAttribute('tabindex')) target.setAttribute('tabindex','-1');
    target.focus({preventScroll:true});
  });
})();
