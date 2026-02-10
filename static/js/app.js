function showStatus(t){
  document.getElementById("status").innerText=t;
}

function cmd(c){
  showStatus("Command → "+c);
  fetch("/cmd",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({cmd:c})
  });
}

/* VOICE */
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recog;

function startMic(){
  if(!SpeechRecognition){
    showStatus("Speech not supported");
    return;
  }

  const btn=document.getElementById("micBtn");
  btn.classList.add("listening");
  showStatus("🎤 Listening...");

  recog=new SpeechRecognition();
  recog.lang="en-IN";

  recog.onresult=e=>{
    const text=e.results[0][0].transcript;
    showStatus("You → "+text);
    fetch("/voice",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({text:text})
    });
  };

  recog.onerror=e=>{
    showStatus("Mic error: "+e.error);
    btn.classList.remove("listening");
  };

  recog.onend=()=>{
    btn.classList.remove("listening");
  };

  recog.start();
}
function toggleAttendance(on){
  fetch("/attendance_mode",{
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body:JSON.stringify({ enable:on })
  });
}

function addStudent(){
  const name = document.getElementById("stuName").value;
  const roll = document.getElementById("stuRoll").value;
  const img  = document.getElementById("stuImage").files[0];

  const fd = new FormData();
  fd.append("name", name);
  fd.append("roll", roll);
  fd.append("image", img);

  fetch("/add_student",{
    method:"POST",
    body: fd
  })
  .then(r=>r.json())
  .then(d=>alert(d.msg));
}
let attendanceOn = false;

function toggleAttendance(){
  attendanceOn = !attendanceOn;

  const btn = document.getElementById("attToggle");
  const box = document.getElementById("registerBox");
  const status = document.getElementById("attStatus");

  if(attendanceOn){
    fetch("/attendance/start");
    btn.innerText = "✅ Attendance ON";
    btn.className = "att-btn on";
    box.style.display = "block";
    status.innerText = "Face recognition & attendance running";
  }else{
    fetch("/attendance/stop");
    btn.innerText = "❌ Attendance OFF";
    btn.className = "att-btn off";
    box.style.display = "none";
    status.innerText = "Attendance system is disabled";
  }
}

function registerStudent(){
  const name = document.getElementById("studentName").value.trim();
  if(!name){
    alert("Enter student name");
    return;
  }

  fetch("/attendance/register", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({name:name})
  });

  document.getElementById("attStatus").innerText =
    "Registering " + name + "… please look at camera";

  document.getElementById("studentName").value = "";
}
function setNeck(angle) {
  document.getElementById("neckVal").innerText =
    "Angle: " + angle + "°";

  fetch("/neck", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ angle: parseInt(angle) })
  });
}