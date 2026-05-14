export function renderIntentTasks(container, tasks, apiFunction, intentText) {
  if (!tasks || tasks.length === 0) {
    container.innerHTML = "";
    return;
  }
  
  const ul = document.createElement("ul");
  ul.dir = "auto";
  ul.style.listStyle = "none";
  ul.style.padding = "0";
  ul.style.margin = "0";
  ul.style.display = "flex";
  ul.style.flexDirection = "column";
  ul.style.gap = "8px";
  ul.style.width = "100%";
  
  tasks.forEach((task, index) => {
    const li = document.createElement("li");
    li.dir = "auto";
    li.className = "intent-task-item";
    li.style.display = "flex";
    li.style.alignItems = "flex-start";
    li.style.gap = "10px";
    li.style.margin = "2px 0";
    li.style.width = "100%";
    li.style.boxSizing = "border-box";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "custom-checkbox";
    checkbox.checked = task.completed;
    
    checkbox.addEventListener("change", async (e) => {
      task.completed = e.target.checked;
      label.style.textDecoration = task.completed ? "line-through" : "none";
      label.style.opacity = task.completed ? "0.5" : "1";
      
      try {
        await apiFunction("POST", "/api/intent", { 
          intent: intentText, 
          intent_tasks: tasks 
        });
      } catch (err) {
        console.error("Failed to update task status", err);
      }
    });
    
    const label = document.createElement("label");
    label.dir = "auto";
    label.textContent = task.text;
    label.style.cursor = "pointer";
    label.style.flex = "1";
    label.style.lineHeight = "1.4";
    label.style.textDecoration = task.completed ? "line-through" : "none";
    label.style.opacity = task.completed ? "0.5" : "1";
    
    label.addEventListener("click", (e) => {
      e.preventDefault();
      checkbox.click();
    });
    
    li.appendChild(checkbox);
    li.appendChild(label);
    ul.appendChild(li);
  });
  
  container.innerHTML = "";
  container.appendChild(ul);
}
